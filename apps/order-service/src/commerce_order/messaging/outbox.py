"""Publish outside DB transactions. Unknown confirmation outcomes retry the same envelope."""

import asyncio
from typing import Protocol

import structlog

from commerce_backend_common.messaging import BrokerError, MessageEnvelope
from commerce_order.messaging.schemas import COMMANDS, MessageInvalid
from commerce_order.repositories.messaging import OutboxRepository
from commerce_order.settings import Settings


class Publisher(Protocol):
    async def publish(
        self, exchange_name: str, routing_key: str, envelope: MessageEnvelope
    ) -> None: ...


class OutboxPublisher:
    def __init__(self, repository: OutboxRepository, broker: Publisher, settings: Settings) -> None:
        self.repository, self.broker, self.settings = repository, broker, settings

    async def once(self) -> int:
        claims = await self.repository.claim(
            self.settings.order_outbox_batch_size,
            self.settings.order_outbox_lease_seconds,
            self.settings.order_outbox_max_attempts,
        )
        sent = 0
        for claim in claims:
            if not await self.repository.owns(claim):
                continue
            permanent = False
            try:
                definition = COMMANDS.get(claim.message.message_type)
                if (
                    claim.exchange != "commerce.commands"
                    or definition is None
                    or definition[0] != claim.routing_key
                ):
                    raise MessageInvalid("OUTBOX_ROUTE_INVALID")
                payload = definition[1].model_validate(claim.message.payload)
                if str(payload.order_id) != claim.message.payload.get("orderId"):
                    raise MessageInvalid("OUTBOX_ORDER_INVALID")
            except ValueError:
                permanent = True
                code = "OUTBOX_MESSAGE_INVALID"
            else:
                try:
                    await self.broker.publish(claim.exchange, claim.routing_key, claim.message)
                except BrokerError:
                    code = "OUTBOX_PUBLISH_UNCONFIRMED"
                else:
                    if await self.repository.published(claim):
                        sent += 1
                    continue
            permanent = permanent or claim.attempt >= self.settings.order_outbox_max_attempts
            delay = min(
                300.0, self.settings.order_worker_poll_seconds * 2 ** min(claim.attempt, 10)
            )
            await self.repository.failed(claim, code, delay, permanent=permanent)
            structlog.get_logger().warning(
                "order_outbox_failed", message_id=str(claim.message.message_id), code=code
            )
        return sent

    async def run(self) -> None:
        while True:
            await self.once()
            await asyncio.sleep(self.settings.order_worker_poll_seconds)
