"""Reconcile stale workflows using original receipts and optimistic fencing."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

import structlog
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_order.clients.recovery import InventorySnapshot, PaymentSnapshot, Snapshot, receipts
from commerce_order.domain.enums import (
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    PaymentStep,
    StockStep,
    WorkflowPhase,
    WorkflowState,
)
from commerce_order.messaging.inbox import InboxProcessor
from commerce_order.messaging.schemas import Event, Payment, PaymentEvidence, PaymentRefundFailed
from commerce_order.models import OrderRecord, OrderWorkflow, OutboxMessage
from commerce_order.models.messaging import OutboxStatus
from commerce_order.repositories.orders import LockedOrder, OrderRepository
from commerce_order.settings import Settings


class SnapshotSource[T: Snapshot](Protocol):
    async def get(self, order_id: UUID, correlation_id: UUID) -> T | None: ...


@dataclass(frozen=True)
class RecoveryClaim:
    order_id: UUID
    version: int
    correlation_id: UUID


def active(locked: LockedOrder) -> bool:
    return (
        locked.order.status
        not in {OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.COMPLETED}
        and locked.workflow.phase != WorkflowPhase.IDLE
    )


class RecoveryJob:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        inventory: SnapshotSource[InventorySnapshot],
        payment: SnapshotSource[PaymentSnapshot],
        settings: Settings,
    ) -> None:
        self.sessions, self.inventory, self.payment, self.settings = (
            sessions,
            inventory,
            payment,
            settings,
        )
        self.inbox = InboxProcessor(sessions)

    async def claim(self) -> list[RecoveryClaim]:
        async with self.sessions() as session, session.begin():
            now: datetime = (await session.execute(select(func.clock_timestamp()))).scalar_one()
            query = (
                select(OrderRecord.id)
                .join(OrderWorkflow, OrderWorkflow.order_id == OrderRecord.id)
                .where(
                    OrderRecord.status.not_in(
                        [OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.COMPLETED]
                    ),
                    OrderWorkflow.phase != WorkflowPhase.IDLE,
                    or_(
                        OrderWorkflow.next_retry_at <= now,
                        and_(
                            OrderWorkflow.next_retry_at.is_(None),
                            OrderWorkflow.updated_at
                            <= now - timedelta(seconds=self.settings.order_recovery_stale_seconds),
                        ),
                    ),
                )
                .order_by(OrderWorkflow.updated_at, OrderRecord.id)
                .limit(self.settings.order_recovery_batch_size)
                .with_for_update(of=OrderRecord, skip_locked=True)
            )
            ids = list(await session.scalars(query))
            claims = []
            for order_id in ids:
                locked = await OrderRepository(session).lock(order_id)
                assert locked is not None
                flow = locked.workflow
                flow.version += 1
                flow.retry_count = min(
                    flow.retry_count + 1, self.settings.order_recovery_max_attempts + 1
                )
                flow.next_retry_at = now + timedelta(
                    seconds=self.settings.order_recovery_lease_seconds
                )
                claims.append(RecoveryClaim(order_id, flow.version, flow.correlation_id))
            return claims

    async def once(self) -> int:
        claims = await self.claim()
        for claim in claims:
            await self.reconcile(claim)
        return len(claims)

    async def reconcile(self, claim: RecoveryClaim) -> None:
        # Claim transaction is finished before either HTTP request starts.
        lookups = await asyncio.gather(
            self.inventory.get(claim.order_id, claim.correlation_id),
            self.payment.get(claim.order_id, claim.correlation_id),
            return_exceptions=True,
        )
        snapshots: list[Snapshot] = []
        reason = None
        for value in lookups:
            if isinstance(value, BaseException):
                reason = "RECOVERY_LOOKUP_UNAVAILABLE"
            elif value is not None:
                snapshots.append(value)
        version = claim.version
        events: list[Event] = []
        try:
            for snapshot in snapshots:
                if snapshot.order_id != claim.order_id:
                    raise ValueError("RECOVERY_ORDER_MISMATCH")
                events.extend(receipts(snapshot))
            async with self.sessions() as session, session.begin():
                locked = await OrderRepository(session).lock(claim.order_id)
                if locked is None or locked.workflow.version != version or not active(locked):
                    return
                for snapshot in snapshots:
                    if isinstance(snapshot, PaymentSnapshot) and snapshot.payment_id is not None:
                        order = locked.order
                        if (
                            snapshot.payment_id not in {order.payment_id, None}
                            and order.payment_id is not None
                        ):
                            raise ValueError("RECOVERY_PAYMENT_MISMATCH")
                        if (
                            snapshot.method != order.payment_method
                            or snapshot.amount != order.total_amount
                            or snapshot.currency != order.currency
                        ):
                            raise ValueError("RECOVERY_AMOUNT_MISMATCH")
                    if (
                        isinstance(snapshot, InventorySnapshot)
                        and locked.workflow.reservation_id is not None
                        and snapshot.reservation_id not in {None, locked.workflow.reservation_id}
                    ):
                        raise ValueError("RECOVERY_RESERVATION_MISMATCH")
            # All snapshot identities are checked before applying any receipt.
            for event in events:
                evidence = None
                if isinstance(event.payload, Payment):
                    for snapshot in snapshots:
                        if (
                            isinstance(snapshot, PaymentSnapshot)
                            and snapshot.payment_id == event.payload.payment_id
                            and snapshot.version == event.payload.payment_version
                            and snapshot.status == event.payload.payment_status
                            and snapshot.payment_id is not None
                            and snapshot.version is not None
                            and snapshot.status is not None
                            and snapshot.method is not None
                            and snapshot.amount is not None
                            and snapshot.currency is not None
                        ):
                            evidence = PaymentEvidence(
                                event.envelope.message_id,
                                snapshot.order_id,
                                snapshot.payment_id,
                                snapshot.version,
                                snapshot.status,
                                snapshot.method,
                                snapshot.amount,
                                snapshot.currency,
                            )
                result = await self.inbox.process(
                    event, expected_workflow_version=version, payment_evidence=evidence
                )
                if result == "superseded":
                    return
                if result == "applied":
                    version += 1
        except Exception:
            reason = "RECOVERY_PROOF_INVALID"
        await self.finish(claim, version, snapshots, events, reason)

    async def finish(
        self,
        claim: RecoveryClaim,
        version: int,
        snapshots: list[Snapshot],
        events: list[Event],
        reason: str | None,
    ) -> None:
        async with self.sessions() as session, session.begin():
            locked = await OrderRepository(session).lock(claim.order_id)
            if locked is None or locked.workflow.version != version or not active(locked):
                return
            order, flow = locked.order, locked.workflow
            if reason != "RECOVERY_PROOF_INVALID":
                for snapshot in snapshots:
                    if (
                        isinstance(snapshot, PaymentSnapshot)
                        and snapshot.status == PaymentStatus.PENDING
                    ):
                        await self.pending_payment(session, locked, snapshot)
                if flow.retry_count <= self.settings.order_recovery_max_attempts:
                    await self.retry_commands(session, locked, events)
            if (
                reason == "RECOVERY_PROOF_INVALID"
                or flow.retry_count >= self.settings.order_recovery_max_attempts
            ):
                order.requires_attention = True
                flow.state = WorkflowState.NEEDS_ATTENTION
                flow.last_error_code = reason or "RECOVERY_STILL_PENDING"
                flow.last_error_message = None
                structlog.get_logger().warning(
                    "order_recovery_attention",
                    order_id=str(order.id),
                    correlation_id=str(flow.correlation_id),
                    phase=flow.phase.value,
                    code=flow.last_error_code,
                )
            delay = min(
                300.0, self.settings.order_recovery_poll_seconds * 2 ** min(flow.retry_count, 8)
            )
            now: datetime = (await session.execute(select(func.clock_timestamp()))).scalar_one()
            flow.next_retry_at = now + timedelta(seconds=delay)
            flow.version += 1

    @staticmethod
    async def pending_payment(
        session: AsyncSession, locked: LockedOrder, snapshot: PaymentSnapshot
    ) -> None:
        order, flow = locked.order, locked.workflow
        if (
            flow.phase != WorkflowPhase.CHECKOUT
            or order.status != OrderStatus.PROCESSING
            or order.payment_method != PaymentMethod.SIMULATED
        ):
            return
        if (
            snapshot.operation_id != flow.payment_operation_id
            or snapshot.command_message_id is None
            or snapshot.payment_id is None
            or snapshot.version is None
        ):
            return
        source = await session.get(OutboxMessage, snapshot.command_message_id)
        if (
            source is None
            or source.aggregate_id != order.id
            or source.message_type != "ProcessPayment"
            or source.payload.get("operationId") != str(snapshot.operation_id)
            or source.correlation_id != flow.correlation_id
        ):
            return
        if order.payment_version is not None and snapshot.version <= order.payment_version:
            return
        order.payment_id, order.payment_version, order.payment_status = (
            snapshot.payment_id,
            snapshot.version,
            PaymentStatus.PENDING,
        )
        order.version += 1
        flow.payment_step = PaymentStep.PENDING

    @staticmethod
    async def retry_commands(
        session: AsyncSession, locked: LockedOrder, events: list[Event]
    ) -> None:
        flow, order = locked.workflow, locked.order
        required: dict[str, UUID | None] = {}
        if flow.phase == WorkflowPhase.CHECKOUT:
            if flow.stock_step == StockStep.RESERVE_PENDING:
                required["ReserveStock"] = flow.reserve_operation_id
            elif (
                flow.stock_step == StockStep.RESERVED
                and flow.payment_step == PaymentStep.INIT_PENDING
            ):
                required[
                    "InitializeCodPayment"
                    if order.payment_method == PaymentMethod.COD
                    else "ProcessPayment"
                ] = flow.payment_operation_id
        elif flow.phase == WorkflowPhase.CANCELLATION:
            if flow.stock_step == StockStep.RELEASE_PENDING:
                required["ReleaseStock"] = flow.release_operation_id
            if flow.payment_step == PaymentStep.CANCEL_PENDING:
                required["CancelCodPayment"] = flow.cancel_payment_operation_id
            elif flow.payment_step == PaymentStep.REFUND_PENDING:
                required["RefundPayment"] = flow.refund_operation_id
        elif flow.phase == WorkflowPhase.DISPATCH:
            required["CommitStock"] = flow.commit_operation_id
        elif flow.phase == WorkflowPhase.COMPLETION:
            required["RecordCodCollection"] = flow.collection_operation_id
        rows = await session.scalars(
            select(OutboxMessage)
            .where(
                OutboxMessage.aggregate_id == order.id,
                OutboxMessage.message_type.in_(list(required)),
            )
            .order_by(OutboxMessage.created_at.desc(), OutboxMessage.id.desc())
            .with_for_update()
        )
        handled: set[str] = set()
        for row in rows:
            if row.message_type in handled or row.payload.get("operationId") != str(
                required.get(row.message_type)
            ):
                continue
            handled.add(row.message_type)
            # A new transport attempt of a retryable refund keeps operation/refund identity.
            failure = next(
                (
                    event
                    for event in reversed(events)
                    if isinstance(event.payload, PaymentRefundFailed)
                    and event.payload.retryable
                    and event.payload.payment_version == order.payment_version
                    and event.envelope.causation_id == row.id
                ),
                None,
            )
            if (
                row.message_type == "RefundPayment"
                and failure is not None
                and row.status in {OutboxStatus.PUBLISHED, OutboxStatus.NEEDS_ATTENTION}
            ):
                session.add(
                    OutboxMessage(
                        message_type=row.message_type,
                        aggregate_type=row.aggregate_type,
                        aggregate_id=row.aggregate_id,
                        exchange_name=row.exchange_name,
                        routing_key=row.routing_key,
                        correlation_id=row.correlation_id,
                        causation_id=failure.envelope.message_id,
                        payload=dict(row.payload),
                    )
                )
                flow.state = WorkflowState.WAITING
            elif (
                row.status == OutboxStatus.PUBLISHED and flow.state != WorkflowState.NEEDS_ATTENTION
            ) or (
                row.status == OutboxStatus.NEEDS_ATTENTION
                and row.last_error in {"OUTBOX_PUBLISH_UNCONFIRMED", "OUTBOX_ATTEMPTS_EXHAUSTED"}
            ):
                row.status, row.attempt_count = OutboxStatus.PENDING, 0
                row.next_attempt_at = func.clock_timestamp()
                row.published_at = None
                row.locked_by = row.locked_until = None

    async def run(self) -> None:
        while True:
            try:
                await self.once()
            except Exception:
                structlog.get_logger().error("order_recovery_iteration_failed")
            await asyncio.sleep(self.settings.order_recovery_poll_seconds)
