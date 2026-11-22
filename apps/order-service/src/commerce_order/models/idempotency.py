"""Persistent HTTP request keys and their original acceptance responses."""

from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from commerce_order.db import SPEC, Base
from commerce_order.domain.enums import OrderAction
from commerce_order.models._common import CreatedAt, UUIDPrimaryKey, enum_type


class IdempotencyRequest(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "idempotency_requests"
    __table_args__ = (
        UniqueConstraint("customer_id", "scope", "idempotency_key"),
        CheckConstraint("length(scope) > 0", name="scope_nonempty"),
        CheckConstraint("length(idempotency_key) > 0", name="key_nonempty"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="request_hash_sha256"),
        CheckConstraint("response_status BETWEEN 100 AND 599", name="http_status_range"),
        CheckConstraint("jsonb_typeof(response_body) = 'object'", name="response_body_object"),
    )

    customer_id: Mapped[UUID] = mapped_column()
    scope: Mapped[str] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SPEC.schema}.orders.id"))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict[str, JsonValue]] = mapped_column(JSONB(none_as_null=True))


class OrderActionRequest(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "order_action_requests"
    __table_args__ = (
        UniqueConstraint("actor_id", "order_id", "action", "idempotency_key"),
        CheckConstraint("length(idempotency_key) > 0", name="key_nonempty"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="request_hash_sha256"),
        CheckConstraint("response_status BETWEEN 100 AND 599", name="http_status_range"),
        CheckConstraint("jsonb_typeof(response_body) = 'object'", name="response_body_object"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SPEC.schema}.orders.id"))
    actor_id: Mapped[UUID] = mapped_column()
    action: Mapped[OrderAction] = mapped_column(enum_type(OrderAction, "action"))
    request_body: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB(none_as_null=True))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict[str, JsonValue]] = mapped_column(JSONB(none_as_null=True))
