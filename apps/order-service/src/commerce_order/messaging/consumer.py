"""RabbitMQ subscription, commit-before-ACK, and durable delayed retries."""

import asyncio
import re
from typing import Any

import aio_pika
import structlog
from aio_pika.abc import AbstractIncomingMessage, AbstractQueue
from pamqp.commands import Basic

from commerce_backend_common.messaging import Broker, PublishUnconfirmed
from commerce_backend_common.messaging_topology import declare_topology
from commerce_order.messaging.inbox import InboxProcessor
from commerce_order.messaging.schemas import MessageInvalid, decode_event
from commerce_order.settings import Settings

RETRY_EXCHANGE = "commerce.order.retry"
RETRY_COUNT = "x-order-retry-count"
ORIGINAL_ROUTE = "x-order-original-routing-key"


class EventConsumer:
    def __init__(self, broker: Broker, processor: InboxProcessor, settings: Settings) -> None:
        self.broker, self.processor, self.settings = broker, processor, settings
        self.queue: AbstractQueue | None = None
        self.failure = asyncio.Event()
        self.started = asyncio.Event()
        self.inflight: set[asyncio.Task[Any]] = set()

    async def prepare(self) -> None:
        channel = await self.broker.ready_channel()
        await declare_topology(channel, "order-service")
        exchange = await channel.declare_exchange(
            RETRY_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )
        for delay in set(self.settings.order_event_retry_delays_ms):
            name = f"order.events.retry.{delay}"
            queue = await channel.declare_queue(
                name,
                durable=True,
                arguments={
                    "x-queue-type": "quorum",
                    "x-dead-letter-strategy": "at-least-once",
                    "x-overflow": "reject-publish",
                    "x-message-ttl": delay,
                    "x-dead-letter-exchange": "",
                    "x-dead-letter-routing-key": "order.events",
                },
            )
            await queue.bind(exchange, routing_key=str(delay))
        self.queue = await channel.get_queue("order.events")

    @staticmethod
    def retry_count(message: AbstractIncomingMessage) -> int:
        count = message.headers.get(RETRY_COUNT, 0)
        if type(count) is not int or count < 0:
            raise MessageInvalid("RETRY_HEADER_INVALID")
        return count

    async def handle(self, message: AbstractIncomingMessage) -> None:
        log = structlog.get_logger()
        try:
            count = self.retry_count(message)
            route = message.routing_key
            if not isinstance(route, str):
                raise MessageInvalid("EVENT_ROUTE_INVALID")
            if message.exchange == "" and route == "order.events":
                original = message.headers.get(ORIGINAL_ROUTE)
                if not isinstance(original, str) or count < 1:
                    raise MessageInvalid("RETRY_ROUTE_INVALID")
                route = original
            event = decode_event(message.body, route, self.settings.broker_max_message_bytes)
            envelope = event.envelope
            if (
                (message.message_id is not None and message.message_id != str(envelope.message_id))
                or (
                    message.correlation_id is not None
                    and message.correlation_id != str(envelope.correlation_id)
                )
                or (message.type is not None and message.type != envelope.message_type)
            ):
                raise MessageInvalid("AMQP_METADATA_MISMATCH")
            await self.processor.process(event)
        except MessageInvalid as exc:
            reason = str(exc) if re.fullmatch(r"[A-Z_]{1,64}", str(exc)) else "EVENT_INVALID"
            log.warning("order_event_rejected", code=reason)
            await self.dead_letter(message, reason)
            return
        except Exception:
            count = self.retry_count(message)
            if count + 1 >= self.settings.order_event_max_attempts:
                log.error("order_event_retry_exhausted", attempts=count + 1)
                await self.dead_letter(message, "EVENT_RETRY_EXHAUSTED")
            else:
                await self.retry(message, count)
                await message.ack()
            return
        await message.ack()  # process() returned only after database commit.

    async def retry(self, message: AbstractIncomingMessage, count: int) -> None:
        channel = await self.broker.ready_channel()
        exchange = await channel.get_exchange(RETRY_EXCHANGE, ensure=False)
        delays = self.settings.order_event_retry_delays_ms
        delay = delays[min(count, len(delays) - 1)]
        route = message.headers.get(ORIGINAL_ROUTE, message.routing_key)
        headers = {
            key: value
            for key, value in message.headers.items()
            if not key.startswith(("x-death", "x-first-death", "x-last-death", "x-delivery-count"))
        }
        headers.update({RETRY_COUNT: count + 1, ORIGINAL_ROUTE: route})
        confirmation = await exchange.publish(
            aio_pika.Message(
                body=message.body,
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                message_id=message.message_id,
                correlation_id=message.correlation_id,
                type=message.type,
                timestamp=message.timestamp,
                headers=headers,
            ),
            routing_key=str(delay),
            mandatory=True,
            timeout=self.settings.broker_publish_timeout_seconds,
        )
        if not isinstance(confirmation, Basic.Ack):
            raise PublishUnconfirmed("Retry publication was not confirmed")

    async def dead_letter(self, message: AbstractIncomingMessage, reason: str) -> None:
        channel = await self.broker.ready_channel()
        exchange = await channel.get_exchange("commerce.dead", ensure=False)
        confirmation = await exchange.publish(
            aio_pika.Message(
                body=message.body,
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                message_id=message.message_id,
                correlation_id=message.correlation_id,
                type=message.type,
                timestamp=message.timestamp,
                headers={**message.headers, "x-order-dead-reason": reason},
            ),
            routing_key="order.events.dead",
            mandatory=True,
            timeout=self.settings.broker_publish_timeout_seconds,
        )
        if not isinstance(confirmation, Basic.Ack):
            raise PublishUnconfirmed("Dead-letter publication was not confirmed")
        await message.ack()

    async def once(self) -> int:
        await self.prepare()
        assert self.queue is not None
        count = 0
        for _ in range(self.settings.order_outbox_batch_size):
            message = await self.queue.get(no_ack=False, fail=False, timeout=5)
            if message is None:
                break
            await self.handle(message)
            count += 1
        return count

    async def callback(self, message: AbstractIncomingMessage) -> None:
        task = asyncio.current_task()
        assert task is not None
        self.inflight.add(task)
        try:
            await self.handle(message)
        except Exception:
            structlog.get_logger().error("order_consumer_transport_failed")
            self.failure.set()
        finally:
            self.inflight.discard(task)

    async def run(self) -> None:
        await self.prepare()
        assert self.queue is not None
        tag = await self.queue.consume(self.callback, no_ack=False)
        self.started.set()
        try:
            await self.failure.wait()
            raise PublishUnconfirmed("Consumer transport stopped before acknowledgement")
        finally:
            try:
                await self.queue.cancel(tag)
            finally:
                if self.inflight:
                    tasks = list(self.inflight)
                    _, pending = await asyncio.wait(tasks, timeout=10)
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
