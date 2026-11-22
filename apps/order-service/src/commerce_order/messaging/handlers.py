"""Apply verified results inside the caller's transaction; no network calls here."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from commerce_order.domain.enums import (
    OrderStatus,
    PaymentMethod,
    PaymentStep,
    StockStep,
    WorkflowPhase,
    WorkflowState,
)
from commerce_order.domain.transitions import TransitionTrigger, transition_target
from commerce_order.messaging.schemas import (
    COMMANDS,
    CodCollected,
    Event,
    EventRetryable,
    MessageInvalid,
    Payment,
    PaymentAmount,
    PaymentCommandRejected,
    PaymentEvidence,
    Reservation,
    StockReservationFailed,
    StockReserved,
)
from commerce_order.models import HistoryActorType, OrderStatusHistory, OutboxMessage
from commerce_order.repositories.orders import LockedOrder, OrderRepository

# Event -> (operation field, command type, expected active phase).
OPERATIONS = {
    "StockReserved": ("reserve_operation_id", "ReserveStock", WorkflowPhase.CHECKOUT),
    "StockReservationFailed": ("reserve_operation_id", "ReserveStock", WorkflowPhase.CHECKOUT),
    "StockReleased": ("release_operation_id", "ReleaseStock", WorkflowPhase.CANCELLATION),
    "StockReleaseFailed": ("release_operation_id", "ReleaseStock", WorkflowPhase.CANCELLATION),
    "StockCommitted": ("commit_operation_id", "CommitStock", WorkflowPhase.DISPATCH),
    "StockCommitFailed": ("commit_operation_id", "CommitStock", WorkflowPhase.DISPATCH),
    "PaymentInitialized": ("payment_operation_id", "InitializeCodPayment", WorkflowPhase.CHECKOUT),
    "PaymentSucceeded": ("payment_operation_id", "ProcessPayment", WorkflowPhase.CHECKOUT),
    "PaymentFailed": ("payment_operation_id", "ProcessPayment", WorkflowPhase.CHECKOUT),
    "CodCollected": ("collection_operation_id", "RecordCodCollection", WorkflowPhase.COMPLETION),
    "CodPaymentCancelled": (
        "cancel_payment_operation_id",
        "CancelCodPayment",
        WorkflowPhase.CANCELLATION,
    ),
    "PaymentRefunded": ("refund_operation_id", "RefundPayment", WorkflowPhase.CANCELLATION),
    "PaymentRefundFailed": ("refund_operation_id", "RefundPayment", WorkflowPhase.CANCELLATION),
}
BY_COMMAND = {command: (field, phase) for field, command, phase in OPERATIONS.values()}


def require(condition: bool, code: str) -> None:
    if not condition:
        raise MessageInvalid(code)


class EventHandlers:
    async def apply(
        self,
        session: AsyncSession,
        locked: LockedOrder,
        event: Event,
        *,
        payment_evidence: PaymentEvidence | None = None,
    ) -> bool:
        order, flow, body = locked.order, locked.workflow, event.payload
        kind = event.envelope.message_type
        command = (
            body.rejected_type if isinstance(body, PaymentCommandRejected) else OPERATIONS[kind][1]
        )
        field, phase = BY_COMMAND[command]
        require(getattr(flow, field) == body.operation_id, "EVENT_OPERATION_MISMATCH")
        require(flow.correlation_id == event.envelope.correlation_id, "EVENT_CORRELATION_MISMATCH")
        source = (
            await session.get(OutboxMessage, event.envelope.causation_id)
            if event.envelope.causation_id
            else None
        )
        require(source is not None, "EVENT_CAUSATION_UNKNOWN")
        assert source is not None
        require(
            source.aggregate_id == order.id
            and source.aggregate_type == "ORDER"
            and source.message_type == command
            and source.message_version == 1
            and source.exchange_name == "commerce.commands"
            and source.routing_key == COMMANDS[command][0]
            and source.correlation_id == flow.correlation_id
            and source.payload.get("operationId") == str(body.operation_id)
            and source.payload.get("orderId") == str(order.id),
            "EVENT_COMMAND_MISMATCH",
        )
        if isinstance(body, StockReserved):
            expected = {
                item.product_id: item.quantity
                for item in await OrderRepository(session).items(order.id)
            }
            require(
                {item.product_id: item.quantity for item in body.items} == expected,
                "EVENT_ITEMS_MISMATCH",
            )
            require(
                flow.reservation_id in {None, body.reservation_id}, "EVENT_RESERVATION_MISMATCH"
            )
            require(flow.stock_step != StockStep.RESERVE_FAILED, "EVENT_RESULT_CONFLICT")
            if (
                flow.reservation_id == body.reservation_id
                and flow.stock_step != StockStep.RESERVE_PENDING
            ):
                return False
        elif isinstance(body, StockReservationFailed):
            expected = {
                item.product_id: item.quantity
                for item in await OrderRepository(session).items(order.id)
            }
            require(
                all(
                    expected.get(row.product_id) == row.requested and row.available < row.requested
                    for row in body.shortages
                ),
                "EVENT_SHORTAGES_MISMATCH",
            )
            if flow.stock_step == StockStep.RESERVE_FAILED:
                require(order.rejection_code == body.code, "EVENT_RESULT_CONFLICT")
                return False
            require(flow.stock_step == StockStep.RESERVE_PENDING, "EVENT_RESULT_CONFLICT")
        elif isinstance(body, Reservation):
            require(flow.reservation_id == body.reservation_id, "EVENT_RESERVATION_MISMATCH")
            if kind == "StockReleased" and flow.stock_step == StockStep.RELEASED:
                return False
            if kind == "StockCommitted" and flow.stock_step == StockStep.COMMITTED:
                return False
        if isinstance(body, Payment):
            expected_method = (
                PaymentMethod.COD
                if kind in {"PaymentInitialized", "CodCollected", "CodPaymentCancelled"}
                else PaymentMethod.SIMULATED
            )
            require(order.payment_method == expected_method, "EVENT_METHOD_MISMATCH")
            require(order.payment_id in {None, body.payment_id}, "EVENT_PAYMENT_MISMATCH")
            if kind not in {"PaymentInitialized", "PaymentSucceeded", "PaymentFailed"}:
                require(order.payment_id is not None, "EVENT_PAYMENT_UNKNOWN")
            if isinstance(body, PaymentAmount):
                require(
                    body.amount == order.total_amount and body.currency == order.currency,
                    "EVENT_AMOUNT_MISMATCH",
                )
            if isinstance(body, CodCollected):
                require(
                    source.payload.get("collectedBy") == str(body.collected_by),
                    "EVENT_COLLECTOR_MISMATCH",
                )
            if order.payment_version is not None:
                if body.payment_version < order.payment_version:
                    return False
                if body.payment_version == order.payment_version:
                    require(order.payment_status == body.payment_status, "EVENT_VERSION_CONFLICT")
                    return False
                if body.payment_version > order.payment_version + 1:
                    verified = payment_evidence is not None and (
                        payment_evidence.message_id == event.envelope.message_id
                        and payment_evidence.order_id == order.id
                        and payment_evidence.payment_id == body.payment_id
                        and payment_evidence.version == body.payment_version
                        and payment_evidence.status == body.payment_status
                        and payment_evidence.method == order.payment_method
                        and payment_evidence.amount == order.total_amount
                        and payment_evidence.currency == order.currency
                    )
                    if not verified:
                        raise EventRetryable("PAYMENT_VERSION_GAP")
        if isinstance(body, PaymentCommandRejected) and body.payment_id is not None:
            require(order.payment_id in {None, body.payment_id}, "EVENT_PAYMENT_MISMATCH")
        require(
            flow.phase == phase
            and flow.state
            in {WorkflowState.RUNNING, WorkflowState.WAITING, WorkflowState.NEEDS_ATTENTION},
            "EVENT_PHASE_MISMATCH",
        )

        if kind == "StockReserved":
            assert isinstance(body, StockReserved)
            require(
                order.status == OrderStatus.PROCESSING
                and flow.stock_step == StockStep.RESERVE_PENDING
                and flow.payment_step == PaymentStep.NOT_REQUESTED,
                "EVENT_STATE_MISMATCH",
            )
            flow.reservation_id, flow.stock_step = body.reservation_id, StockStep.RESERVED
            flow.retry_count, flow.next_retry_at = 0, None
            flow.payment_operation_id = uuid4()
            flow.payment_step = PaymentStep.INIT_PENDING
            self.command(
                session,
                locked,
                event,
                "InitializeCodPayment"
                if order.payment_method == PaymentMethod.COD
                else "ProcessPayment",
                {
                    "operationId": str(flow.payment_operation_id),
                    "customerId": str(order.customer_id),
                    "amount": str(order.total_amount),
                    "currency": order.currency,
                },
            )
        elif kind == "StockReservationFailed":
            assert isinstance(body, StockReservationFailed)
            flow.stock_step = StockStep.RESERVE_FAILED
            order.rejection_code = body.code
            self.change(session, locked, event, TransitionTrigger.RESERVATION_FAILED)
            self.idle(locked)
        elif kind in {"PaymentInitialized", "PaymentSucceeded"}:
            assert isinstance(body, Payment)
            require(
                flow.payment_step in {PaymentStep.INIT_PENDING, PaymentStep.PENDING},
                "EVENT_STATE_MISMATCH",
            )
            self.payment(locked, body)
            flow.payment_step = (
                PaymentStep.COD_READY if kind == "PaymentInitialized" else PaymentStep.PAID
            )
            self.change(session, locked, event, TransitionTrigger.CHECKOUT_READY)
            self.idle(locked)
        elif kind == "PaymentFailed":
            assert isinstance(body, Payment)
            require(
                flow.payment_step in {PaymentStep.INIT_PENDING, PaymentStep.PENDING},
                "EVENT_STATE_MISMATCH",
            )
            self.payment(locked, body)
            order.cancel_reason = "PAYMENT_FAILED"
            flow.payment_step = PaymentStep.FAILED
            self.change(session, locked, event, TransitionTrigger.PAYMENT_FAILED)
            flow.phase, flow.state = WorkflowPhase.CANCELLATION, WorkflowState.WAITING
            flow.stock_step, flow.release_operation_id = StockStep.RELEASE_PENDING, uuid4()
            self.command(
                session,
                locked,
                event,
                "ReleaseStock",
                {
                    "operationId": str(flow.release_operation_id),
                    "reservationId": str(flow.reservation_id),
                    "reason": "PAYMENT_FAILED",
                },
            )
        elif kind == "StockReleased":
            require(flow.stock_step == StockStep.RELEASE_PENDING, "EVENT_STATE_MISMATCH")
            flow.stock_step = StockStep.RELEASED
            self.finish_cancellation(session, locked, event)
        elif kind == "StockCommitted":
            require(flow.stock_step == StockStep.COMMIT_PENDING, "EVENT_STATE_MISMATCH")
            flow.stock_step = StockStep.COMMITTED
            self.change(session, locked, event, TransitionTrigger.STOCK_COMMITTED)
            order.dispatched_at = datetime.now(UTC)
            self.idle(locked)
        elif kind == "CodCollected":
            assert isinstance(body, Payment)
            require(flow.payment_step == PaymentStep.COLLECT_PENDING, "EVENT_STATE_MISMATCH")
            self.payment(locked, body)
            flow.payment_step = PaymentStep.PAID
            self.change(session, locked, event, TransitionTrigger.DELIVERY_COMPLETED)
            order.completed_at = datetime.now(UTC)
            self.idle(locked)
        elif kind in {"CodPaymentCancelled", "PaymentRefunded"}:
            assert isinstance(body, Payment)
            require(
                flow.payment_step
                == (
                    PaymentStep.CANCEL_PENDING
                    if kind == "CodPaymentCancelled"
                    else PaymentStep.REFUND_PENDING
                ),
                "EVENT_STATE_MISMATCH",
            )
            self.payment(locked, body)
            flow.payment_step = (
                PaymentStep.CANCELLED if kind == "CodPaymentCancelled" else PaymentStep.REFUNDED
            )
            self.finish_cancellation(session, locked, event)
        elif kind == "PaymentRefundFailed":
            assert isinstance(body, Payment)
            require(flow.payment_step == PaymentStep.REFUND_PENDING, "EVENT_STATE_MISMATCH")
            self.payment(locked, body)
            self.attention(locked, "PAYMENT_REFUND_FAILED")
        else:
            require(
                kind in {"StockReleaseFailed", "StockCommitFailed", "PaymentCommandRejected"},
                "EVENT_UNHANDLED",
            )
            if kind != "PaymentCommandRejected":
                require(
                    flow.stock_step
                    == (
                        StockStep.RELEASE_PENDING
                        if kind == "StockReleaseFailed"
                        else StockStep.COMMIT_PENDING
                    ),
                    "EVENT_STATE_MISMATCH",
                )
            self.attention(locked, "DEPENDENCY_COMMAND_REJECTED")
        return True

    @staticmethod
    def payment(locked: LockedOrder, body: Payment) -> None:
        locked.order.payment_id, locked.order.payment_version = (
            body.payment_id,
            body.payment_version,
        )
        locked.order.payment_status = body.payment_status

    @staticmethod
    def attention(locked: LockedOrder, code: str) -> None:
        locked.order.requires_attention = True
        locked.workflow.state = WorkflowState.NEEDS_ATTENTION
        locked.workflow.last_error_code = code
        locked.workflow.last_error_message = None

    @staticmethod
    def idle(locked: LockedOrder) -> None:
        locked.workflow.phase, locked.workflow.state = WorkflowPhase.IDLE, WorkflowState.DONE
        locked.order.requires_attention = False
        locked.workflow.last_error_code = locked.workflow.last_error_message = None
        locked.workflow.retry_count, locked.workflow.next_retry_at = 0, None

    @staticmethod
    def change(
        session: AsyncSession, locked: LockedOrder, event: Event, trigger: TransitionTrigger
    ) -> None:
        previous = locked.order.status
        target = transition_target(
            locked.facts(), trigger, delivered=trigger == TransitionTrigger.DELIVERY_COMPLETED
        )
        locked.order.status = target
        session.add(
            OrderStatusHistory(
                order_id=locked.order.id,
                from_status=previous,
                to_status=target,
                actor_type=HistoryActorType.SYSTEM,
                actor_id=None,
                reason=locked.order.rejection_code
                if trigger == TransitionTrigger.RESERVATION_FAILED
                else locked.order.cancel_reason
                if trigger
                in {TransitionTrigger.PAYMENT_FAILED, TransitionTrigger.CANCELLATION_COMPLETED}
                else None,
                correlation_id=event.envelope.correlation_id,
                message_id=event.envelope.message_id,
            )
        )

    def finish_cancellation(self, session: AsyncSession, locked: LockedOrder, event: Event) -> None:
        flow = locked.workflow
        if flow.stock_step == StockStep.RELEASED and flow.payment_step in {
            PaymentStep.CANCELLED,
            PaymentStep.REFUNDED,
            PaymentStep.FAILED,
        }:
            self.change(session, locked, event, TransitionTrigger.CANCELLATION_COMPLETED)
            locked.order.cancelled_at = datetime.now(UTC)
            self.idle(locked)

    @staticmethod
    def command(
        session: AsyncSession, locked: LockedOrder, event: Event, kind: str, values: dict[str, str]
    ) -> None:
        session.add(
            OutboxMessage(
                message_type=kind,
                aggregate_type="ORDER",
                aggregate_id=locked.order.id,
                exchange_name="commerce.commands",
                routing_key=COMMANDS[kind][0],
                correlation_id=event.envelope.correlation_id,
                causation_id=event.envelope.message_id,
                payload={"orderId": str(locked.order.id), **values},
            )
        )
