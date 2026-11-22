"""Pure action/transition guards; callers must verify events and lock/version DB state."""

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from commerce_order.domain.enums import (
    ActorRole,
    OrderAction,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    StockStep,
    WorkflowPhase,
    WorkflowState,
)


@dataclass(frozen=True)
class Actor:
    user_id: UUID
    role: ActorRole


@dataclass(frozen=True)
class OrderFacts:
    """Trusted current state, not values accepted from the checkout request."""

    customer_id: UUID
    status: OrderStatus
    payment_method: PaymentMethod
    payment_status: PaymentStatus | None
    stock_step: StockStep
    workflow_phase: WorkflowPhase
    workflow_state: WorkflowState


class OrderRuleViolation(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class TransitionTrigger(StrEnum):
    CHECKOUT_READY = "CHECKOUT_READY"
    RESERVATION_FAILED = "RESERVATION_FAILED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"
    STOCK_COMMITTED = "STOCK_COMMITTED"
    DELIVERY_COMPLETED = "DELIVERY_COMPLETED"
    CANCELLATION_COMPLETED = "CANCELLATION_COMPLETED"


TRANSITIONS = MappingProxyType(
    {
        (
            OrderStatus.PROCESSING,
            TransitionTrigger.CHECKOUT_READY,
        ): OrderStatus.AWAITING_CONFIRMATION,
        (OrderStatus.PROCESSING, TransitionTrigger.RESERVATION_FAILED): OrderStatus.REJECTED,
        (OrderStatus.PROCESSING, TransitionTrigger.PAYMENT_FAILED): OrderStatus.CANCELLING,
        (OrderStatus.AWAITING_CONFIRMATION, TransitionTrigger.CONFIRM): OrderStatus.PREPARING,
        (OrderStatus.AWAITING_CONFIRMATION, TransitionTrigger.CANCEL): OrderStatus.CANCELLING,
        (OrderStatus.PREPARING, TransitionTrigger.CANCEL): OrderStatus.CANCELLING,
        (OrderStatus.PREPARING, TransitionTrigger.STOCK_COMMITTED): OrderStatus.SHIPPING,
        (OrderStatus.SHIPPING, TransitionTrigger.DELIVERY_COMPLETED): OrderStatus.COMPLETED,
        (OrderStatus.CANCELLING, TransitionTrigger.CANCELLATION_COMPLETED): OrderStatus.CANCELLED,
    }
)


def payment_ready(order: OrderFacts) -> bool:
    if order.payment_method == PaymentMethod.COD:
        return order.payment_status == PaymentStatus.AWAITING_COLLECTION
    return (
        order.payment_method == PaymentMethod.SIMULATED
        and order.payment_status == PaymentStatus.SUCCEEDED
    )


def _idle(order: OrderFacts) -> bool:
    return order.workflow_phase == WorkflowPhase.IDLE and order.workflow_state == WorkflowState.DONE


def _active(order: OrderFacts, phase: WorkflowPhase) -> bool:
    # A valid late result can finish a workflow previously flagged for attention.
    return order.workflow_phase == phase and order.workflow_state in {
        WorkflowState.RUNNING,
        WorkflowState.WAITING,
        WorkflowState.NEEDS_ATTENTION,
    }


def _action_allowed(order: OrderFacts, actor: Actor, action: OrderAction) -> bool:
    if actor.role not in {ActorRole.CUSTOMER, ActorRole.ADMIN}:
        return False
    if actor.role == ActorRole.CUSTOMER and actor.user_id != order.customer_id:
        return False
    is_admin = actor.role == ActorRole.ADMIN
    if action == OrderAction.RECORD_EXCEPTION:
        # A note does not dispatch, collect, release or complete the order.
        return is_admin and order.status == OrderStatus.SHIPPING
    if not _idle(order):
        return False
    if not payment_ready(order):
        return False
    if action == OrderAction.COMPLETE:
        return (
            is_admin
            and order.status == OrderStatus.SHIPPING
            and order.stock_step == StockStep.COMMITTED
        )
    if order.stock_step != StockStep.RESERVED:
        return False
    if action == OrderAction.CANCEL:
        return order.status == OrderStatus.AWAITING_CONFIRMATION or (
            is_admin and order.status == OrderStatus.PREPARING
        )
    if action == OrderAction.CONFIRM:
        return is_admin and order.status == OrderStatus.AWAITING_CONFIRMATION
    if action == OrderAction.DISPATCH:
        return is_admin and order.status == OrderStatus.PREPARING
    return False


def allowed_actions(order: OrderFacts, actor: Actor) -> tuple[OrderAction, ...]:
    """Use the same guards for the public view and for accepting the actual action."""
    return tuple(action for action in OrderAction if _action_allowed(order, actor, action))


def ensure_action_allowed(order: OrderFacts, actor: Actor, action: OrderAction) -> None:
    if actor.role == ActorRole.CUSTOMER and actor.user_id != order.customer_id:
        raise OrderRuleViolation("NOT_FOUND")
    if actor.role != ActorRole.ADMIN and action != OrderAction.CANCEL:
        raise OrderRuleViolation("FORBIDDEN")
    if not _action_allowed(order, actor, action):
        raise OrderRuleViolation("ORDER_STATE_CONFLICT")


def transition_target(
    order: OrderFacts,
    trigger: TransitionTrigger,
    *,
    actor: Actor | None = None,
    delivered: bool = False,
) -> OrderStatus:
    """Check an edge AND its evidence; this function never mutates or persists state.

    Facts must reflect the verified result before calling this guard. For example,
    STOCK_COMMITTED needs stock_step=COMMITTED and the current phase=DISPATCH.
    Message identity/version/deduplication and HTTP replay belong to later layers.
    """
    target = TRANSITIONS.get((order.status, trigger))
    if target is None:
        raise OrderRuleViolation("ORDER_STATE_CONFLICT")
    if trigger in {TransitionTrigger.CONFIRM, TransitionTrigger.CANCEL}:
        if actor is None:
            raise OrderRuleViolation("AUTH_REQUIRED")
        action = OrderAction.CONFIRM if trigger == TransitionTrigger.CONFIRM else OrderAction.CANCEL
        ensure_action_allowed(order, actor, action)
        return target
    valid = False
    if trigger == TransitionTrigger.CHECKOUT_READY:
        valid = (
            _active(order, WorkflowPhase.CHECKOUT)
            and order.stock_step == StockStep.RESERVED
            and payment_ready(order)
        )
    elif trigger == TransitionTrigger.RESERVATION_FAILED:
        valid = (
            _active(order, WorkflowPhase.CHECKOUT)
            and order.stock_step == StockStep.RESERVE_FAILED
            and order.payment_status is None
        )
    elif trigger == TransitionTrigger.PAYMENT_FAILED:
        valid = (
            _active(order, WorkflowPhase.CHECKOUT)
            and order.payment_method == PaymentMethod.SIMULATED
            and order.stock_step == StockStep.RESERVED
            and order.payment_status == PaymentStatus.FAILED
        )
    elif trigger == TransitionTrigger.STOCK_COMMITTED:
        valid = (
            _active(order, WorkflowPhase.DISPATCH)
            and order.stock_step == StockStep.COMMITTED
            and payment_ready(order)
        )
    elif trigger == TransitionTrigger.DELIVERY_COMPLETED:
        phase_valid = _active(order, WorkflowPhase.COMPLETION) or (
            order.payment_method == PaymentMethod.SIMULATED and _idle(order)
        )
        valid = (
            delivered is True
            and phase_valid
            and order.stock_step == StockStep.COMMITTED
            and order.payment_status == PaymentStatus.SUCCEEDED
        )
    elif trigger == TransitionTrigger.CANCELLATION_COMPLETED:
        settled = (
            order.payment_status == PaymentStatus.CANCELLED
            if order.payment_method == PaymentMethod.COD
            else order.payment_status in {PaymentStatus.REFUNDED, PaymentStatus.FAILED}
        )
        valid = (
            _active(order, WorkflowPhase.CANCELLATION)
            and order.stock_step == StockStep.RELEASED
            and settled
        )
    if not valid:
        raise OrderRuleViolation("ORDER_STATE_CONFLICT")
    return target
