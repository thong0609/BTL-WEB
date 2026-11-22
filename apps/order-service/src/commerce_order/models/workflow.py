"""Durable coordination state, including external reservation references."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from commerce_order.db import SPEC, Base
from commerce_order.domain.enums import PaymentStep, StockStep, WorkflowPhase, WorkflowState
from commerce_order.models._common import Timestamps, enum_type


class OrderWorkflow(Timestamps, Base):
    __tablename__ = "order_workflows"
    __table_args__ = (
        CheckConstraint("retry_count >= 0", name="retry_count_nonnegative"),
        CheckConstraint("version >= 0", name="version_nonnegative"),
        Index("ix_order_workflows_state_next_retry", "state", "next_retry_at"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SPEC.schema}.orders.id"), primary_key=True)
    phase: Mapped[WorkflowPhase] = mapped_column(enum_type(WorkflowPhase, "phase"))
    state: Mapped[WorkflowState] = mapped_column(enum_type(WorkflowState, "state", 20))
    stock_step: Mapped[StockStep] = mapped_column(enum_type(StockStep, "stock_step"))
    payment_step: Mapped[PaymentStep] = mapped_column(enum_type(PaymentStep, "payment_step"))
    reservation_id: Mapped[UUID | None] = mapped_column(Uuid)
    reserve_operation_id: Mapped[UUID | None] = mapped_column(Uuid)
    release_operation_id: Mapped[UUID | None] = mapped_column(Uuid)
    commit_operation_id: Mapped[UUID | None] = mapped_column(Uuid)
    payment_operation_id: Mapped[UUID | None] = mapped_column(Uuid)
    refund_operation_id: Mapped[UUID | None] = mapped_column(Uuid)
    cancel_payment_operation_id: Mapped[UUID | None] = mapped_column(Uuid)
    collection_operation_id: Mapped[UUID | None] = mapped_column(Uuid)
    correlation_id: Mapped[UUID] = mapped_column(Uuid)
    retry_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default=text("0"))
