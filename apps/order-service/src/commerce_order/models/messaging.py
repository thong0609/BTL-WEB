"""Order-owned durable inbox/outbox records used by explicit business workers."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from commerce_order.db import Base
from commerce_order.models._common import CreatedAt, UUIDPrimaryKey, enum_type


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PUBLISHED = "PUBLISHED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


class ProcessedMessage(Base):
    __tablename__ = "processed_messages"
    __table_args__ = (
        CheckConstraint("length(consumer_name) > 0", name="consumer_nonempty"),
        CheckConstraint("message_version >= 1", name="message_version_positive"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
    )

    consumer_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    message_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    message_type: Mapped[str] = mapped_column(String(100))
    message_version: Mapped[int] = mapped_column(Integer)
    payload_hash: Mapped[str] = mapped_column(String(64))
    correlation_id: Mapped[UUID] = mapped_column(Uuid)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OutboxMessage(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        CheckConstraint("message_version >= 1", name="message_version_positive"),
        CheckConstraint("aggregate_version >= 0", name="aggregate_version_nonnegative"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        CheckConstraint(
            "aggregate_type IN ('ORDER', 'RESERVATION', 'PAYMENT', 'REFUND')", name="aggregate_type"
        ),
        CheckConstraint(
            "exchange_name IN ('commerce.commands', 'commerce.events')", name="exchange_name"
        ),
        Index("ix_outbox_messages_status_next_attempt_id", "status", "next_attempt_at", "id"),
        Index("ix_outbox_messages_locked_until", "locked_until"),
        Index("ix_outbox_messages_aggregate", "aggregate_type", "aggregate_id"),
    )

    message_type: Mapped[str] = mapped_column(String(100))
    message_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    aggregate_type: Mapped[str] = mapped_column(String(50))
    aggregate_id: Mapped[UUID] = mapped_column(Uuid)
    aggregate_version: Mapped[int | None] = mapped_column(Integer)
    exchange_name: Mapped[str] = mapped_column(String(100))
    routing_key: Mapped[str] = mapped_column(String(150))
    correlation_id: Mapped[UUID] = mapped_column(Uuid)
    causation_id: Mapped[UUID | None] = mapped_column(Uuid)
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSONB(none_as_null=True))
    status: Mapped[OutboxStatus] = mapped_column(
        enum_type(OutboxStatus, "status", 20), server_default=text("'PENDING'")
    )
    attempt_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
