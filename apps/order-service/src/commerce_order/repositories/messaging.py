"""Short database transactions for outbox claiming and fenced completion."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from commerce_backend_common.messaging import MessageEnvelope
from commerce_order.models.messaging import OutboxMessage, OutboxStatus


@dataclass(frozen=True)
class Claim:
    message: MessageEnvelope
    exchange: str
    routing_key: str
    token: str
    attempt: int


class OutboxRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def claim(self, limit: int, lease_seconds: float, max_attempts: int) -> list[Claim]:
        async with self.sessions() as session, session.begin():
            now: datetime = (await session.execute(select(func.clock_timestamp()))).scalar_one()
            records = await session.scalars(
                select(OutboxMessage)
                .where(
                    or_(
                        and_(
                            OutboxMessage.status == OutboxStatus.PENDING,
                            OutboxMessage.next_attempt_at <= func.clock_timestamp(),
                        ),
                        and_(
                            OutboxMessage.status == OutboxStatus.PROCESSING,
                            OutboxMessage.locked_until <= func.clock_timestamp(),
                        ),
                    )
                )
                .order_by(OutboxMessage.next_attempt_at, OutboxMessage.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            result = []
            for row in records:
                if row.aggregate_type != "ORDER" or row.payload.get("orderId") != str(
                    row.aggregate_id
                ):
                    row.status = OutboxStatus.NEEDS_ATTENTION
                    row.last_error = "OUTBOX_AGGREGATE_INVALID"
                    row.locked_by = row.locked_until = None
                    continue
                if row.attempt_count >= max_attempts:
                    row.status = OutboxStatus.NEEDS_ATTENTION
                    row.last_error = "OUTBOX_ATTEMPTS_EXHAUSTED"
                    row.locked_by = row.locked_until = None
                    continue
                try:
                    envelope = MessageEnvelope(
                        message_id=row.id,
                        message_type=row.message_type,
                        version=row.message_version,
                        correlation_id=row.correlation_id,
                        causation_id=row.causation_id,
                        occurred_at=row.created_at,
                        payload=row.payload,
                    )
                except ValueError:
                    row.status = OutboxStatus.NEEDS_ATTENTION
                    row.last_error = "OUTBOX_ENVELOPE_INVALID"
                    row.locked_by = row.locked_until = None
                    continue
                row.status = OutboxStatus.PROCESSING
                row.attempt_count += 1
                row.locked_by = (
                    uuid4().hex
                )  # New ownership token on every claim, including takeover.
                row.locked_until = now + timedelta(seconds=lease_seconds)
                result.append(
                    Claim(
                        envelope,
                        row.exchange_name,
                        row.routing_key,
                        row.locked_by,
                        row.attempt_count,
                    )
                )
            return result

    @staticmethod
    def fence(claim: Claim) -> ColumnElement[bool]:
        return and_(
            OutboxMessage.id == claim.message.message_id,
            OutboxMessage.status == OutboxStatus.PROCESSING,
            OutboxMessage.locked_by == claim.token,
            OutboxMessage.locked_until > func.clock_timestamp(),
        )

    async def owns(self, claim: Claim) -> bool:
        async with self.sessions() as session:
            return bool(await session.scalar(select(OutboxMessage.id).where(self.fence(claim))))

    async def published(self, claim: Claim) -> bool:
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                update(OutboxMessage)
                .where(self.fence(claim))
                .values(
                    status=OutboxStatus.PUBLISHED,
                    published_at=func.clock_timestamp(),
                    locked_by=None,
                    locked_until=None,
                    last_error=None,
                )
                .returning(OutboxMessage.id)
            )
            return result.scalar_one_or_none() is not None

    async def failed(self, claim: Claim, code: str, delay: float, *, permanent: bool) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(
                update(OutboxMessage)
                .where(self.fence(claim))
                .values(
                    status=OutboxStatus.NEEDS_ATTENTION if permanent else OutboxStatus.PENDING,
                    next_attempt_at=func.clock_timestamp() + timedelta(seconds=delay),
                    locked_by=None,
                    locked_until=None,
                    last_error=code,
                )
            )
