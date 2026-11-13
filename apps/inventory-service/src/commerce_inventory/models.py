"""Inventory-owned persistence models; external IDs never use cross-service FKs.

These models describe storage constraints. Locking, version comparisons, immutable
history and valid state transitions must also be enforced by the use cases.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from commerce_inventory.db import SPEC, Base


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UpdatedAtMixin:
    # ORM updates refresh this field; raw SQL writers must set it explicitly.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StockItem(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "stock_items"
    __table_args__ = (
        CheckConstraint("on_hand_quantity >= 0", name="on_hand_nonnegative"),
        CheckConstraint("reserved_quantity >= 0", name="reserved_nonnegative"),
        CheckConstraint("reserved_quantity <= on_hand_quantity", name="reserved_within_on_hand"),
        CheckConstraint("low_stock_threshold >= 0", name="threshold_nonnegative"),
        CheckConstraint("version >= 0", name="version_nonnegative"),
    )

    product_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    on_hand_quantity: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    reserved_quantity: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    low_stock_threshold: Mapped[int] = mapped_column(Integer, server_default=text("5"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    @hybrid_property
    def available_quantity(self) -> int:
        """Derived availability, usable on loaded instances and in SQL queries."""
        return self.on_hand_quantity - self.reserved_quantity


class Reservation(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("status IN ('RESERVED', 'RELEASED', 'COMMITTED')", name="status_valid"),
        CheckConstraint("version >= 0", name="version_nonnegative"),
        CheckConstraint(
            "(status = 'RESERVED' AND released_at IS NULL AND committed_at IS NULL) OR "
            "(status = 'RELEASED' AND released_at IS NOT NULL AND committed_at IS NULL) OR "
            "(status = 'COMMITTED' AND committed_at IS NOT NULL AND released_at IS NULL)",
            name="status_timestamps_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReservationItem(CreatedAtMixin, Base):
    __tablename__ = "reservation_items"
    __table_args__ = (
        UniqueConstraint("reservation_id", "product_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SPEC.schema}.reservations.id"))
    product_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SPEC.schema}.stock_items.product_id"))
    quantity: Mapped[int] = mapped_column(Integer)


class InventoryOperation(CreatedAtMixin, Base):
    __tablename__ = "inventory_operations"
    __table_args__ = (
        CheckConstraint(
            "operation_type IN ('RESERVE', 'RELEASE', 'COMMIT', 'ADJUST', 'INITIALIZE')",
            name="operation_type_valid",
        ),
        CheckConstraint("result_status IN ('SUCCEEDED', 'REJECTED')", name="result_status_valid"),
        Index("ix_inventory_operations_order_id", "order_id"),
    )

    # Supplied by the caller, preserved on retries; never generated here.
    operation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    order_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    operation_type: Mapped[str] = mapped_column(String(20))
    request_hash: Mapped[str] = mapped_column(String(64))
    result_status: Mapped[str] = mapped_column(String(20))
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))


class StockMovement(CreatedAtMixin, Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        UniqueConstraint("operation_id", "product_id"),
        CheckConstraint(
            "movement_type IN ('RECEIPT', 'ADJUSTMENT', 'RESERVE', 'RELEASE', 'COMMIT')",
            name="movement_type_valid",
        ),
        CheckConstraint("actor_type IN ('USER', 'SYSTEM')", name="actor_type_valid"),
        CheckConstraint("on_hand_after >= 0", name="on_hand_after_nonnegative"),
        CheckConstraint(
            "reserved_after >= 0 AND reserved_after <= on_hand_after",
            name="reserved_after_valid",
        ),
        Index("ix_stock_movements_product_id_created_at", "product_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    operation_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SPEC.schema}.inventory_operations.operation_id")
    )
    product_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SPEC.schema}.stock_items.product_id"))
    reservation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SPEC.schema}.reservations.id")
    )
    movement_type: Mapped[str] = mapped_column(String(20))
    on_hand_delta: Mapped[int] = mapped_column(Integer)
    reserved_delta: Mapped[int] = mapped_column(Integer)
    on_hand_after: Mapped[int] = mapped_column(Integer)
    reserved_after: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class ProcessedMessage(Base):
    __tablename__ = "processed_messages"
    __table_args__ = (CheckConstraint("message_version > 0", name="message_version_positive"),)

    consumer_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    message_type: Mapped[str] = mapped_column(String(100))
    message_version: Mapped[int] = mapped_column(Integer)
    payload_hash: Mapped[str] = mapped_column(String(64))
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OutboxMessage(CreatedAtMixin, Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'PUBLISHED', 'NEEDS_ATTENTION')",
            name="status_valid",
        ),
        CheckConstraint("message_version > 0", name="message_version_positive"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint(
            "aggregate_version IS NULL OR aggregate_version >= 0",
            name="aggregate_version_nonnegative",
        ),
        Index("ix_outbox_messages_status_next_attempt_at", "status", "next_attempt_at"),
        Index("ix_outbox_messages_locked_until", "locked_until"),
        Index("ix_outbox_messages_aggregate_type_aggregate_id", "aggregate_type", "aggregate_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    message_type: Mapped[str] = mapped_column(String(100))
    message_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    aggregate_type: Mapped[str] = mapped_column(String(50))
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    aggregate_version: Mapped[int | None] = mapped_column(Integer)
    exchange_name: Mapped[str] = mapped_column(String(100))
    routing_key: Mapped[str] = mapped_column(String(150))
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    causation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'PENDING'"))
    attempt_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
