"""AMQP transport only: no inbox/outbox, business handlers or automatic publish retries."""

import asyncio
import logging
import ssl
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import aio_pika
from aio_pika.abc import AbstractExchange, AbstractRobustChannel
from pamqp.commands import Basic
from pydantic import ConfigDict, Field, JsonValue, field_validator
from yarl import URL

from commerce_backend_common.schemas import ApiModel, UtcDatetime
from commerce_backend_common.settings import ServiceSettings


class BrokerError(RuntimeError):
    """Safe public error text; never wrap raw connection/credential text in the message."""


class BrokerConfigurationError(BrokerError):
    pass


class BrokerUnavailable(BrokerError):
    pass


class PublishUnconfirmed(BrokerError):
    """Broker outcome can be unknown; do not assume the message was not accepted."""


class MessageUnroutable(BrokerError):
    pass


class MessageEnvelope(ApiModel):
    model_config = ConfigDict(extra="ignore")
    message_id: UUID
    message_type: str = Field(alias="type", pattern=r"^[A-Z][A-Za-z0-9]{0,99}$")
    version: Literal[1]
    correlation_id: UUID
    causation_id: UUID | None
    occurred_at: UtcDatetime
    payload: dict[str, JsonValue]

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Message version must be an integer")
        return value

    @classmethod
    def new(
        cls, message_type: str, correlation_id: UUID, payload: dict[str, JsonValue]
    ) -> "MessageEnvelope":
        return cls(
            message_id=uuid4(),
            message_type=message_type,
            version=1,
            correlation_id=correlation_id,
            causation_id=None,
            occurred_at=datetime.now(UTC),
            payload=payload,
        )


def parse_envelope(body: bytes, max_bytes: int = 262144) -> MessageEnvelope:
    if len(body) > max_bytes:
        raise BrokerError("Message exceeds the configured size limit")
    return MessageEnvelope.model_validate_json(body)


def broker_url(settings: ServiceSettings) -> URL:
    if not settings.broker_url:
        raise BrokerConfigurationError("BROKER_URL is required")
    try:
        url = URL(settings.broker_url.get_secret_value())
        if (
            url.scheme not in {"amqp", "amqps"}
            or not url.host
            or not url.user
            or not url.password
            or url.query_string
            or url.fragment
        ):
            raise ValueError
        _ = url.port
        if settings.app_env == "test" and url.host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError
        return url
    except (ValueError, TypeError):
        raise BrokerConfigurationError(
            "Use an AMQP(S) URL with credentials and no query/fragment"
        ) from None


class Broker:
    def __init__(self, settings: ServiceSettings, *, role: str = "api") -> None:
        self.settings = settings
        self._url = broker_url(settings)
        self._role = role
        self.connection: aio_pika.RobustConnection | None = None
        self.channel: aio_pika.RobustChannel | None = None
        self._open_lock = asyncio.Lock()
        self._closed = False

    async def open(self) -> None:
        async with self._open_lock:
            if self._closed:
                raise BrokerUnavailable("Broker client is closed")
            if self.connection is not None and not self.connection.is_closed:
                return
            # Emit sanitized status at our boundary instead of library reconnect URLs.
            for name in ("aio_pika", "aiormq"):
                logging.getLogger(name).setLevel(logging.CRITICAL + 1)
            context = None
            if self._url.scheme == "amqps":
                context = ssl.create_default_context()
                if self.settings.broker_ssl_ca_file:
                    try:
                        context.load_verify_locations(
                            str(self.settings.broker_ssl_ca_file.resolve())
                        )
                    except (OSError, ssl.SSLError):
                        raise BrokerConfigurationError(
                            "Cannot load broker CA certificate"
                        ) from None
            connection = aio_pika.RobustConnection(
                self._url,
                ssl_context=context,
                reconnect_interval=self.settings.broker_reconnect_interval_seconds,
                heartbeat=self.settings.broker_heartbeat_seconds,
                fail_fast=True,
                client_properties={"connection_name": f"{self.settings.service_name}-{self._role}"},
            )
            try:
                await connection.connect(timeout=self.settings.broker_connect_timeout_seconds)
                channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
                if not isinstance(channel, aio_pika.RobustChannel):
                    raise BrokerUnavailable("Expected a reconnecting channel")
                await channel.set_qos(prefetch_count=self.settings.broker_prefetch_count)
            except BaseException as exc:
                await connection.close()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                if not isinstance(exc, Exception):
                    raise
                raise BrokerUnavailable("Unable to connect to broker") from None
            self.connection = connection
            self.channel = channel

    async def ready_channel(self) -> AbstractRobustChannel:
        await self.open()
        if self.connection is None or self.channel is None:
            raise BrokerUnavailable("Broker is not connected")
        await self.connection.ready()
        await self.channel.ready()
        return self.channel

    async def readiness(self) -> str:
        try:
            async with asyncio.timeout(self.settings.broker_connect_timeout_seconds):
                await self.ready_channel()
            return "ready"
        except BrokerConfigurationError:
            return "invalid_configuration"
        except Exception:
            return "unavailable"

    async def publish(
        self, exchange_name: str, routing_key: str, envelope: MessageEnvelope
    ) -> None:
        body = envelope.model_dump_json().encode("utf-8")
        if len(body) > self.settings.broker_max_message_bytes:
            raise BrokerError("Message exceeds the configured size limit")
        try:
            async with asyncio.timeout(self.settings.broker_publish_timeout_seconds):
                channel = await self.ready_channel()
                exchange: AbstractExchange = await channel.get_exchange(exchange_name, ensure=False)
                confirmation = await exchange.publish(
                    aio_pika.Message(
                        body=body,
                        content_type="application/json",
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        message_id=str(envelope.message_id),
                        correlation_id=str(envelope.correlation_id),
                        type=envelope.message_type,
                        timestamp=envelope.occurred_at,
                        headers={"schema_version": envelope.version},
                    ),
                    routing_key=routing_key,
                    mandatory=True,
                    timeout=self.settings.broker_publish_timeout_seconds,
                )
                if not isinstance(confirmation, Basic.Ack):
                    raise PublishUnconfirmed("Broker did not positively confirm publication")
        except aio_pika.exceptions.PublishError:
            raise MessageUnroutable(
                "Message was returned because no queue accepted its routing"
            ) from None
        except BrokerError:
            raise
        except Exception:
            raise PublishUnconfirmed("Publication failed or outcome is unknown") from None

    async def close(self) -> None:
        self._closed = True
        if self.connection is not None:
            await self.connection.close()
