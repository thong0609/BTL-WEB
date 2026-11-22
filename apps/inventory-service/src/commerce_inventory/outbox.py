"""Claim with a lease, publish outside the DB transaction, then confirm ownership."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select, update

from commerce_backend_common.database import Database
from commerce_backend_common.messaging import Broker, MessageEnvelope
from commerce_inventory.models import OutboxMessage


async def publish_one(database: Database, broker: Broker) -> bool:
    owner = str(uuid4())
    async with database.session() as session, session.begin():
        now = datetime.now(UTC)
        row = await session.scalar(
            select(OutboxMessage)
            .where(
                or_(
                    and_(OutboxMessage.status == "PENDING", OutboxMessage.next_attempt_at <= now),
                    and_(OutboxMessage.status == "PROCESSING", OutboxMessage.locked_until <= now),
                )
            )
            .order_by(OutboxMessage.next_attempt_at, OutboxMessage.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return False
        event = MessageEnvelope(
            message_id=row.id,
            message_type=row.message_type,
            version=1,
            correlation_id=row.correlation_id,
            causation_id=row.causation_id,
            occurred_at=row.created_at,
            payload=row.payload,
        )
        row.attempt_count += 1
        row.status = "PROCESSING"
        row.locked_by = owner
        # Broker.publish bounds the complete attempt to <= 30 seconds. The lease
        # leaves margin for the result transaction without holding a DB connection.
        row.locked_until = now + timedelta(seconds=60)
        exchange, route, attempt = row.exchange_name, row.routing_key, row.attempt_count
    values: dict[str, object] = {"locked_by": None, "locked_until": None}
    try:
        await broker.publish(exchange, route, event)
    except Exception:
        values.update(
            status="PENDING",
            last_error="Publication failed or confirmation was not received",
            next_attempt_at=datetime.now(UTC) + timedelta(seconds=min(300, 2 ** min(attempt, 8))),
        )
    else:
        values.update(status="PUBLISHED", published_at=datetime.now(UTC), last_error=None)
    async with database.session() as session, session.begin():
        # A stale worker must never overwrite a newer worker's claim/result.
        await session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.id == event.message_id,
                OutboxMessage.status == "PROCESSING",
                OutboxMessage.locked_by == owner,
            )
            .values(**values)
        )
    return True
