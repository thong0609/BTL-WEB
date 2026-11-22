"""Order headers, immutable purchase snapshots and append-only status history."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from commerce_order.db import SPEC, Base
from commerce_order.domain.enums import OrderStatus, PaymentMethod, PaymentStatus
from commerce_order.models._common import CreatedAt, Timestamps, UUIDPrimaryKey, enum_type


class HistoryActorType(StrEnum):
    CUSTOMER = "CUSTOMER"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"


class OrderRecord(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("order_number"),
        CheckConstraint("subtotal_amount >= 0", name="subtotal_nonnegative"),
        CheckConstraint("shipping_fee_amount >= 0", name="shipping_fee_nonnegative"),
        CheckConstraint("total_amount >= 0", name="total_nonnegative"),
        CheckConstraint("total_amount = subtotal_amount + shipping_fee_amount", name="total_sum"),
        CheckConstraint("currency = 'VND'", name="currency_vnd"),
        CheckConstraint("version >= 0", name="version_nonnegative"),
        CheckConstraint("payment_version >= 0", name="payment_version_nonnegative"),
        Index("ix_orders_customer_created_id", "customer_id", "created_at", "id"),
        Index("ix_orders_status_created_id", "status", "created_at", "id"),
        Index("ix_orders_created_id", "created_at", "id"),
    )

    order_number: Mapped[str] = mapped_column(String(32))
    customer_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[OrderStatus] = mapped_column(enum_type(OrderStatus, "status"))
    payment_method: Mapped[PaymentMethod] = mapped_column(
        enum_type(PaymentMethod, "payment_method", 20)
    )
    payment_id: Mapped[UUID | None] = mapped_column(Uuid)
    payment_status: Mapped[PaymentStatus | None] = mapped_column(
        enum_type(PaymentStatus, "payment_status")
    )
    payment_version: Mapped[int | None] = mapped_column(Integer)
    recipient_name: Mapped[str] = mapped_column(String(150))
    recipient_phone: Mapped[str] = mapped_column(String(30))
    shipping_address: Mapped[str] = mapped_column(Text)
    customer_note: Mapped[str | None] = mapped_column(Text)
    subtotal_amount: Mapped[int] = mapped_column(BigInteger)
    shipping_fee_amount: Mapped[int] = mapped_column(BigInteger)
    total_amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'VND'"))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    rejection_code: Mapped[str | None] = mapped_column(String(64))
    requires_attention: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    exception_note: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderItem(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "product_id", name="uq_order_items_order_product"),
        UniqueConstraint("order_id", "product_sku", name="uq_order_items_order_sku"),
        CheckConstraint("quantity BETWEEN 1 AND 999", name="quantity_range"),
        CheckConstraint("catalog_version >= 0", name="catalog_version_nonnegative"),
        CheckConstraint("unit_price_amount >= 0", name="unit_price_nonnegative"),
        CheckConstraint("line_total_amount >= 0", name="line_total_nonnegative"),
        CheckConstraint(
            "line_total_amount = unit_price_amount * quantity", name="line_total_product"
        ),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SPEC.schema}.orders.id"))
    product_id: Mapped[UUID] = mapped_column(Uuid)
    product_sku: Mapped[str] = mapped_column(String(64))
    product_name: Mapped[str] = mapped_column(String(200))
    catalog_version: Mapped[int] = mapped_column(Integer)
    unit_price_amount: Mapped[int] = mapped_column(BigInteger)
    quantity: Mapped[int] = mapped_column(Integer)
    line_total_amount: Mapped[int] = mapped_column(BigInteger)


class OrderStatusHistory(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "order_status_history"
    __table_args__ = (
        Index("ix_order_status_history_order_created_id", "order_id", "created_at", "id"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SPEC.schema}.orders.id"))
    from_status: Mapped[OrderStatus | None] = mapped_column(enum_type(OrderStatus, "from_status"))
    to_status: Mapped[OrderStatus] = mapped_column(enum_type(OrderStatus, "to_status"))
    actor_type: Mapped[HistoryActorType] = mapped_column(
        enum_type(HistoryActorType, "actor_type", 20)
    )
    actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    reason: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[UUID] = mapped_column(Uuid)
    message_id: Mapped[UUID | None] = mapped_column(Uuid)
