"""HTTP actions write state/history/commands atomically under the persistence lock."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from commerce_order.api.schemas import Complete, Reason
from commerce_order.domain.enums import (
    ActorRole,
    OrderAction,
    PaymentMethod,
    PaymentStep,
    StockStep,
    WorkflowPhase,
    WorkflowState,
)
from commerce_order.domain.transitions import (
    Actor,
    OrderRuleViolation,
    TransitionTrigger,
    transition_target,
)
from commerce_order.messaging.schemas import COMMANDS
from commerce_order.models import HistoryActorType, OrderStatusHistory, OutboxMessage
from commerce_order.repositories.orders import LockedOrder
from commerce_order.services.idempotency import ActionPayload
from commerce_order.services.persistence import OrderPersistence, StoredResponse


class OrderActions:
    def __init__(self, persistence: OrderPersistence) -> None:
        self.persistence = persistence

    async def accept(
        self, actor: Actor, order_id: UUID, action: OrderAction, key: str, payload: ActionPayload
    ) -> StoredResponse:
        async def apply(session: AsyncSession, locked: LockedOrder) -> StoredResponse:
            order, flow = locked.order, locked.workflow
            if action == OrderAction.CONFIRM:
                self.change(session, locked, actor, TransitionTrigger.CONFIRM)
                order.confirmed_at = datetime.now(UTC)
            elif action == OrderAction.CANCEL:
                assert isinstance(payload, Reason)
                if flow.reservation_id is None or order.payment_id is None:
                    raise OrderRuleViolation("ORDER_STATE_CONFLICT")
                self.change(session, locked, actor, TransitionTrigger.CANCEL, payload.reason)
                order.cancel_reason = payload.reason
                flow.phase, flow.state = WorkflowPhase.CANCELLATION, WorkflowState.WAITING
                flow.release_operation_id, flow.stock_step = uuid4(), StockStep.RELEASE_PENDING
                self.command(
                    session,
                    locked,
                    "ReleaseStock",
                    {
                        "operationId": str(flow.release_operation_id),
                        "reservationId": str(flow.reservation_id),
                        "reason": payload.reason,
                    },
                )
                if order.payment_method == PaymentMethod.COD:
                    flow.cancel_payment_operation_id, flow.payment_step = (
                        uuid4(),
                        PaymentStep.CANCEL_PENDING,
                    )
                    self.command(
                        session,
                        locked,
                        "CancelCodPayment",
                        {
                            "operationId": str(flow.cancel_payment_operation_id),
                            "paymentId": str(order.payment_id),
                            "reason": payload.reason,
                        },
                    )
                else:
                    flow.refund_operation_id, flow.payment_step = (
                        uuid4(),
                        PaymentStep.REFUND_PENDING,
                    )
                    self.command(
                        session,
                        locked,
                        "RefundPayment",
                        {
                            "operationId": str(flow.refund_operation_id),
                            "paymentId": str(order.payment_id),
                            "amount": str(order.total_amount),
                            "currency": order.currency,
                            "reason": payload.reason,
                        },
                    )
            elif action == OrderAction.DISPATCH:
                if flow.reservation_id is None:
                    raise OrderRuleViolation("ORDER_STATE_CONFLICT")
                flow.phase, flow.state = WorkflowPhase.DISPATCH, WorkflowState.WAITING
                flow.commit_operation_id, flow.stock_step = uuid4(), StockStep.COMMIT_PENDING
                self.command(
                    session,
                    locked,
                    "CommitStock",
                    {
                        "operationId": str(flow.commit_operation_id),
                        "reservationId": str(flow.reservation_id),
                    },
                )
            elif action == OrderAction.COMPLETE:
                assert isinstance(payload, Complete)
                if order.payment_method == PaymentMethod.COD:
                    if order.payment_id is None:
                        raise OrderRuleViolation("ORDER_STATE_CONFLICT")
                    flow.phase, flow.state = WorkflowPhase.COMPLETION, WorkflowState.WAITING
                    flow.collection_operation_id, flow.payment_step = (
                        uuid4(),
                        PaymentStep.COLLECT_PENDING,
                    )
                    self.command(
                        session,
                        locked,
                        "RecordCodCollection",
                        {
                            "operationId": str(flow.collection_operation_id),
                            "paymentId": str(order.payment_id),
                            "collectedBy": str(actor.user_id),
                        },
                    )
                else:
                    self.change(session, locked, actor, TransitionTrigger.DELIVERY_COMPLETED)
                    order.completed_at = datetime.now(UTC)
            elif action == OrderAction.RECORD_EXCEPTION:
                assert isinstance(payload, Reason)
                order.requires_attention, order.exception_note = True, payload.reason
                # The action record keeps reason/actor/time; no fictitious status transition.
            status = 200 if action in {OrderAction.CONFIRM, OrderAction.RECORD_EXCEPTION} else 202
            return StoredResponse(
                status,
                {
                    "orderId": str(order.id),
                    "status": order.status.value,
                    "workflowState": flow.state.value,
                },
            )

        return await self.persistence.accept_action(actor, order_id, action, key, payload, apply)

    @staticmethod
    def change(
        session: AsyncSession,
        locked: LockedOrder,
        actor: Actor,
        trigger: TransitionTrigger,
        reason: str | None = None,
    ) -> None:
        previous = locked.order.status
        target = transition_target(
            locked.facts(),
            trigger,
            actor=actor,
            delivered=trigger == TransitionTrigger.DELIVERY_COMPLETED,
        )
        locked.order.status = target
        session.add(
            OrderStatusHistory(
                order_id=locked.order.id,
                from_status=previous,
                to_status=target,
                actor_type=HistoryActorType.ADMIN
                if actor.role == ActorRole.ADMIN
                else HistoryActorType.CUSTOMER,
                actor_id=actor.user_id,
                reason=reason,
                correlation_id=locked.workflow.correlation_id,
            )
        )

    @staticmethod
    def command(
        session: AsyncSession, locked: LockedOrder, kind: str, values: dict[str, str]
    ) -> None:
        session.add(
            OutboxMessage(
                message_type=kind,
                aggregate_type="ORDER",
                aggregate_id=locked.order.id,
                exchange_name="commerce.commands",
                routing_key=COMMANDS[kind][0],
                correlation_id=locked.workflow.correlation_id,
                payload={"orderId": str(locked.order.id), **values},
            )
        )
