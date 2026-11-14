"""Payment tables owned by commerce_payments. No cross-service foreign keys."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv

from commerce_payment.db import Base

_SCHEMA = Base.metadata.schema


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        CheckConstraint("amount >= 0", name=conv("ck_payment_attempts_amount")),
        CheckConstraint("currency = 'VND'", name=conv("ck_payment_attempts_currency")),
        CheckConstraint("version >= 1", name=conv("ck_payment_attempts_version")),
        CheckConstraint(
            "("
            "method = 'COD' AND simulation_scenario IS NULL AND ("
            "(status = 'AWAITING_COLLECTION' AND collection_operation_id IS NULL "
            "AND cancel_operation_id IS NULL AND collected_by IS NULL "
            "AND succeeded_at IS NULL AND failed_at IS NULL AND cancelled_at IS NULL "
            "AND failure_code IS NULL AND resolve_after IS NULL) "
            "OR (status = 'SUCCEEDED' AND collection_operation_id IS NOT NULL "
            "AND collected_by IS NOT NULL AND succeeded_at IS NOT NULL "
            "AND failed_at IS NULL AND cancelled_at IS NULL AND cancel_operation_id IS NULL "
            "AND failure_code IS NULL AND resolve_after IS NULL) "
            "OR (status = 'CANCELLED' AND cancel_operation_id IS NOT NULL "
            "AND cancelled_at IS NOT NULL AND collection_operation_id IS NULL "
            "AND collected_by IS NULL AND succeeded_at IS NULL AND failed_at IS NULL "
            "AND failure_code IS NULL AND resolve_after IS NULL)"
            ")"
            ") OR ("
            "method = 'SIMULATED' AND collected_by IS NULL AND collection_operation_id IS NULL "
            "AND cancel_operation_id IS NULL AND cancelled_at IS NULL "
            "AND simulation_scenario IS NOT NULL AND ("
            "(status = 'PENDING' AND simulation_scenario IN ('DELAYED_SUCCESS', 'DELAYED_FAILURE') "
            "AND resolve_after IS NOT NULL AND succeeded_at IS NULL AND failed_at IS NULL "
            "AND failure_code IS NULL) "
            "OR (status IN ('SUCCEEDED', 'REFUND_PENDING', 'REFUNDED') "
            "AND simulation_scenario IN ('SUCCESS', 'DELAYED_SUCCESS') "
            "AND succeeded_at IS NOT NULL AND failed_at IS NULL AND failure_code IS NULL "
            "AND resolve_after IS NULL) "
            "OR (status = 'FAILED' AND simulation_scenario IN ('FAILURE', 'DELAYED_FAILURE') "
            "AND failed_at IS NOT NULL AND failure_code IS NOT NULL AND succeeded_at IS NULL "
            "AND resolve_after IS NULL)"
            ")"
            ")",
            name=conv("ck_payment_attempts_state"),
        ),
        Index("ix_payment_attempts_status_resolve_after", "status", "resolve_after"),
        Index("ix_payment_attempts_customer_id_created_at", "customer_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    order_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    customer_id: Mapped[UUID] = mapped_column(Uuid)
    operation_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="VND")
    status: Mapped[str] = mapped_column(String(30))
    simulation_scenario: Mapped[str | None] = mapped_column(String(30))
    resolve_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    collection_operation_id: Mapped[UUID | None] = mapped_column(Uuid, unique=True)
    cancel_operation_id: Mapped[UUID | None] = mapped_column(Uuid, unique=True)
    collected_by: Mapped[UUID | None] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefundAttempt(Base):
    __tablename__ = "refund_attempts"
    __table_args__ = (
        CheckConstraint("amount >= 0", name=conv("ck_refund_attempts_amount")),
        CheckConstraint("currency = 'VND'", name=conv("ck_refund_attempts_currency")),
        CheckConstraint("retry_count >= 0", name=conv("ck_refund_attempts_retry_count")),
        CheckConstraint("version >= 1", name=conv("ck_refund_attempts_version")),
        CheckConstraint(
            "status IN ('PENDING', 'SUCCEEDED', 'NEEDS_ATTENTION')",
            name=conv("ck_refund_attempts_status"),
        ),
        CheckConstraint(
            "simulation_scenario IN ('SUCCESS', 'DELAYED_SUCCESS', 'FAIL_UNTIL_RETRY')",
            name=conv("ck_refund_attempts_scenario"),
        ),
        CheckConstraint(
            "(status = 'SUCCEEDED' AND completed_at IS NOT NULL) "
            "OR (status IN ('PENDING', 'NEEDS_ATTENTION') AND completed_at IS NULL)",
            name=conv("ck_refund_attempts_completion"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    payment_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey(f"{_SCHEMA}.payment_attempts.id", ondelete="RESTRICT"), unique=True
    )
    operation_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="VND")
    status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    simulation_scenario: Mapped[str] = mapped_column(String(30))
    retry_count: Mapped[int] = mapped_column(Integer)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentStatusHistory(Base):
    __tablename__ = "payment_status_history"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('PAYMENT', 'REFUND')",
            name=conv("ck_payment_status_history_entity"),
        ),
        CheckConstraint(
            "actor_type IN ('SYSTEM', 'ADMIN')",
            name=conv("ck_payment_status_history_actor"),
        ),
        CheckConstraint(
            "(entity_type = 'PAYMENT' AND refund_id IS NULL) "
            "OR (entity_type = 'REFUND' AND refund_id IS NOT NULL)",
            name=conv("ck_payment_status_history_target"),
        ),
        Index("ix_payment_status_history_payment_id_created_at", "payment_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    payment_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey(f"{_SCHEMA}.payment_attempts.id", ondelete="RESTRICT")
    )
    refund_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{_SCHEMA}.refund_attempts.id", ondelete="RESTRICT")
    )
    entity_type: Mapped[str] = mapped_column(String(20))
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    operation_id: Mapped[UUID] = mapped_column(Uuid)
    message_id: Mapped[UUID | None] = mapped_column(Uuid)
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DemoConfiguration(Base):
    __tablename__ = "demo_configuration"
    __table_args__ = (
        CheckConstraint("id = 1", name=conv("ck_demo_configuration_singleton")),
        CheckConstraint(
            "payment_scenario IN ('SUCCESS', 'FAILURE', 'DELAYED_SUCCESS', 'DELAYED_FAILURE')",
            name=conv("ck_demo_configuration_payment_scenario"),
        ),
        CheckConstraint(
            "refund_scenario IN ('SUCCESS', 'DELAYED_SUCCESS', 'FAIL_UNTIL_RETRY')",
            name=conv("ck_demo_configuration_refund_scenario"),
        ),
        CheckConstraint(
            "delay_seconds BETWEEN 0 AND 300",
            name=conv("ck_demo_configuration_delay"),
        ),
        CheckConstraint("version >= 1", name=conv("ck_demo_configuration_version")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    payment_scenario: Mapped[str] = mapped_column(String(30))
    refund_scenario: Mapped[str] = mapped_column(String(30))
    delay_seconds: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DemoConfigurationHistory(Base):
    __tablename__ = "demo_configuration_history"
    __table_args__ = (
        CheckConstraint("version >= 1", name=conv("ck_demo_configuration_history_version")),
        Index(
            "uq_demo_configuration_history_configuration_id_version",
            "configuration_id",
            "version",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    configuration_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(f"{_SCHEMA}.demo_configuration.id", ondelete="RESTRICT")
    )
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProcessedMessage(Base):
    __tablename__ = "processed_messages"

    consumer_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    message_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    message_type: Mapped[str] = mapped_column(String(100))
    message_version: Mapped[int] = mapped_column(Integer)
    payload_hash: Mapped[str] = mapped_column(String(64))
    correlation_id: Mapped[UUID] = mapped_column(Uuid)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'PUBLISHED', 'NEEDS_ATTENTION')",
            name=conv("ck_outbox_messages_status"),
        ),
        CheckConstraint("attempt_count >= 0", name=conv("ck_outbox_messages_attempt_count")),
        CheckConstraint("message_version >= 1", name=conv("ck_outbox_messages_version")),
        Index("ix_outbox_messages_status_next_attempt_at", "status", "next_attempt_at"),
        Index("ix_outbox_messages_locked_until", "locked_until"),
        Index(
            "ix_outbox_messages_aggregate",
            "aggregate_type",
            "aggregate_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    message_type: Mapped[str] = mapped_column(String(100))
    message_version: Mapped[int] = mapped_column(Integer)
    aggregate_type: Mapped[str] = mapped_column(String(50))
    aggregate_id: Mapped[UUID] = mapped_column(Uuid)
    aggregate_version: Mapped[int | None] = mapped_column(Integer)
    exchange_name: Mapped[str] = mapped_column(String(100))
    routing_key: Mapped[str] = mapped_column(String(150))
    correlation_id: Mapped[UUID] = mapped_column(Uuid)
    causation_id: Mapped[UUID | None] = mapped_column(Uuid)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20))
    attempt_count: Mapped[int] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
