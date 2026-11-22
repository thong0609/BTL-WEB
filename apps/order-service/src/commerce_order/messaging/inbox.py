"""Inbox and business effects commit atomically before a transport ACK."""

import hashlib
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_order.domain.transitions import OrderRuleViolation
from commerce_order.messaging.handlers import EventHandlers
from commerce_order.messaging.schemas import Event, MessageInvalid, PaymentEvidence
from commerce_order.models import ProcessedMessage
from commerce_order.repositories.orders import OrderRepository

CONSUMER = "order.events.v1"


class InboxProcessor:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], handlers: EventHandlers | None = None
    ) -> None:
        self.sessions = sessions
        self.handlers = handlers or EventHandlers()

    async def process(
        self,
        event: Event,
        *,
        expected_workflow_version: int | None = None,
        payment_evidence: PaymentEvidence | None = None,
    ) -> Literal["duplicate", "applied", "ignored", "superseded"]:
        envelope = event.envelope
        if payment_evidence is not None and expected_workflow_version is None:
            raise MessageInvalid("RECOVERY_FENCE_REQUIRED")
        async with self.sessions() as session, session.begin():
            # Also serialize the same messageId if a corrupt redelivery changes orderId.
            key = int.from_bytes(
                hashlib.sha256((CONSUMER + str(envelope.message_id)).encode()).digest()[:8],
                signed=True,
            )
            await session.execute(
                text("SELECT pg_advisory_xact_lock(CAST(:key AS BIGINT))"), {"key": key}
            )
            old = await session.get(ProcessedMessage, (CONSUMER, envelope.message_id))
            if old is not None:
                if old.payload_hash != event.digest:
                    raise MessageInvalid("MESSAGE_ID_CONFLICT")
                return "duplicate"
            locked = await OrderRepository(session).lock(event.payload.order_id)
            if locked is None:
                raise MessageInvalid("EVENT_ORDER_UNKNOWN")
            if (
                expected_workflow_version is not None
                and locked.workflow.version != expected_workflow_version
            ):
                return "superseded"
            try:
                if payment_evidence is None:
                    changed = await self.handlers.apply(session, locked, event)
                else:
                    changed = await self.handlers.apply(
                        session, locked, event, payment_evidence=payment_evidence
                    )
            except OrderRuleViolation:
                raise MessageInvalid("EVENT_STATE_CONFLICT") from None
            if changed:
                locked.order.version += 1
                locked.workflow.version += 1
            session.add(
                ProcessedMessage(
                    consumer_name=CONSUMER,
                    message_id=envelope.message_id,
                    message_type=envelope.message_type,
                    message_version=envelope.version,
                    payload_hash=event.digest,
                    correlation_id=envelope.correlation_id,
                )
            )
            await session.flush()
            return "applied" if changed else "ignored"
