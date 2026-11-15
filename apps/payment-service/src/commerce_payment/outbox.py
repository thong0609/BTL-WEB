"""Publish committed outbox rows through the broker transport."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from commerce_backend_common.messaging import (
    Broker,
    MessageEnvelope,
    MessageUnroutable,
    PublishUnconfirmed,
)
from commerce_payment.models import OutboxMessage


async def publish_pending(session: AsyncSession, broker: Broker, *, limit: int = 20) -> int:
    now = datetime.now(UTC)
    published = 0
    async with session.begin():
        rows = (
            await session.scalars(
                select(OutboxMessage)
                .where(
                    OutboxMessage.status == "PENDING",
                    OutboxMessage.next_attempt_at <= now,
                )
                .order_by(OutboxMessage.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()

    for row in rows:
        envelope = MessageEnvelope.model_validate(
            {
                "messageId": str(row.id),
                "type": row.message_type,
                "version": row.message_version,
                "correlationId": str(row.correlation_id),
                "causationId": None if row.causation_id is None else str(row.causation_id),
                "occurredAt": row.created_at.isoformat().replace("+00:00", "Z"),
                "payload": row.payload,
            }
        )
        try:
            await broker.publish(row.exchange_name, row.routing_key, envelope)
        except (PublishUnconfirmed, MessageUnroutable) as exc:
            async with session.begin():
                locked = await session.get(OutboxMessage, row.id, with_for_update=True)
                if locked is None:
                    continue
                locked.attempt_count += 1
                locked.last_error = type(exc).__name__
                locked.next_attempt_at = now + timedelta(
                    seconds=min(60, 2 ** min(locked.attempt_count, 6))
                )
            continue
        async with session.begin():
            locked = await session.get(OutboxMessage, row.id, with_for_update=True)
            if locked is None:
                continue
            locked.status = "PUBLISHED"
            locked.published_at = now
            locked.last_error = None
            published += 1
    return published
