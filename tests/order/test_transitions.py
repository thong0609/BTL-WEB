from dataclasses import replace
from uuid import UUID

import pytest

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
from commerce_order.domain.transitions import (
    Actor,
    OrderFacts,
    OrderRuleViolation,
    TransitionTrigger,
    allowed_actions,
    ensure_action_allowed,
    transition_target,
)

CUSTOMER_ID = UUID("10000000-0000-4000-8000-000000000001")
CUSTOMER = Actor(CUSTOMER_ID, ActorRole.CUSTOMER)
OTHER_CUSTOMER = Actor(UUID("10000000-0000-4000-8000-000000000002"), ActorRole.CUSTOMER)
ADMIN = Actor(UUID("10000000-0000-4000-8000-000000000003"), ActorRole.ADMIN)
BASE = OrderFacts(
    customer_id=CUSTOMER_ID,
    status=OrderStatus.AWAITING_CONFIRMATION,
    payment_method=PaymentMethod.COD,
    payment_status=PaymentStatus.AWAITING_COLLECTION,
    stock_step=StockStep.RESERVED,
    workflow_phase=WorkflowPhase.IDLE,
    workflow_state=WorkflowState.DONE,
)


@pytest.mark.parametrize(
    "actor,status,stock,expected",
    [
        (CUSTOMER, OrderStatus.AWAITING_CONFIRMATION, StockStep.RESERVED, {OrderAction.CANCEL}),
        (OTHER_CUSTOMER, OrderStatus.AWAITING_CONFIRMATION, StockStep.RESERVED, set()),
        (
            ADMIN,
            OrderStatus.AWAITING_CONFIRMATION,
            StockStep.RESERVED,
            {OrderAction.CANCEL, OrderAction.CONFIRM},
        ),
        (CUSTOMER, OrderStatus.PREPARING, StockStep.RESERVED, set()),
        (
            ADMIN,
            OrderStatus.PREPARING,
            StockStep.RESERVED,
            {OrderAction.CANCEL, OrderAction.DISPATCH},
        ),
        (
            ADMIN,
            OrderStatus.SHIPPING,
            StockStep.COMMITTED,
            {OrderAction.COMPLETE, OrderAction.RECORD_EXCEPTION},
        ),
        (CUSTOMER, OrderStatus.SHIPPING, StockStep.COMMITTED, set()),
        (ADMIN, OrderStatus.CANCELLED, StockStep.RELEASED, set()),
        (ADMIN, OrderStatus.COMPLETED, StockStep.COMMITTED, set()),
    ],
)
def test_actions_match_actor_ownership_and_order_stage(actor, status, stock, expected):
    order = replace(BASE, status=status, stock_step=stock)
    assert set(allowed_actions(order, actor)) == expected
    for action in expected:
        ensure_action_allowed(order, actor, action)


@pytest.mark.parametrize(
    "phase,state",
    [
        (WorkflowPhase.DISPATCH, WorkflowState.WAITING),
        (WorkflowPhase.COMPLETION, WorkflowState.RUNNING),
        (WorkflowPhase.CANCELLATION, WorkflowState.NEEDS_ATTENTION),
        (WorkflowPhase.IDLE, WorkflowState.WAITING),
    ],
)
def test_busy_workflow_blocks_conflicting_http_actions(phase, state):
    order = replace(BASE, workflow_phase=phase, workflow_state=state)
    assert allowed_actions(order, ADMIN) == ()
    with pytest.raises(OrderRuleViolation, match="ORDER_STATE_CONFLICT"):
        ensure_action_allowed(order, ADMIN, OrderAction.CANCEL)


def test_action_guard_preserves_not_found_and_forbidden():
    with pytest.raises(OrderRuleViolation, match="NOT_FOUND"):
        ensure_action_allowed(BASE, OTHER_CUSTOMER, OrderAction.CANCEL)
    with pytest.raises(OrderRuleViolation, match="FORBIDDEN"):
        ensure_action_allowed(BASE, CUSTOMER, OrderAction.CONFIRM)


def test_admin_can_record_a_shipping_exception_while_collection_is_pending():
    order = replace(
        BASE,
        status=OrderStatus.SHIPPING,
        stock_step=StockStep.COMMITTED,
        workflow_phase=WorkflowPhase.COMPLETION,
        workflow_state=WorkflowState.WAITING,
    )
    assert allowed_actions(order, ADMIN) == (OrderAction.RECORD_EXCEPTION,)
    ensure_action_allowed(order, ADMIN, OrderAction.RECORD_EXCEPTION)
    with pytest.raises(OrderRuleViolation):
        ensure_action_allowed(order, ADMIN, OrderAction.COMPLETE)


@pytest.mark.parametrize("payment", [None, PaymentStatus.PENDING, PaymentStatus.REFUND_PENDING])
def test_unresolved_money_cannot_be_cancelled_or_dispatched(payment):
    order = replace(BASE, status=OrderStatus.PREPARING, payment_status=payment)
    assert allowed_actions(order, ADMIN) == ()


@pytest.mark.parametrize(
    "method,payment",
    [
        (PaymentMethod.COD, PaymentStatus.AWAITING_COLLECTION),
        (PaymentMethod.SIMULATED, PaymentStatus.SUCCEEDED),
    ],
)
def test_checkout_waits_for_both_stock_and_the_correct_payment_result(method, payment):
    order = replace(
        BASE,
        status=OrderStatus.PROCESSING,
        payment_method=method,
        payment_status=payment,
        workflow_phase=WorkflowPhase.CHECKOUT,
        workflow_state=WorkflowState.WAITING,
    )
    assert (
        transition_target(order, TransitionTrigger.CHECKOUT_READY)
        == OrderStatus.AWAITING_CONFIRMATION
    )
    for changes in (
        {"stock_step": StockStep.RESERVE_PENDING},
        {"payment_status": PaymentStatus.PENDING},
    ):
        with pytest.raises(OrderRuleViolation):
            transition_target(replace(order, **changes), TransitionTrigger.CHECKOUT_READY)


@pytest.mark.parametrize(
    "method,payment",
    [
        (PaymentMethod.COD, PaymentStatus.SUCCEEDED),
        (PaymentMethod.SIMULATED, PaymentStatus.AWAITING_COLLECTION),
    ],
)
def test_checkout_cannot_confuse_cod_and_simulated_payment_results(method, payment):
    order = replace(
        BASE,
        status=OrderStatus.PROCESSING,
        payment_method=method,
        payment_status=payment,
        workflow_phase=WorkflowPhase.CHECKOUT,
        workflow_state=WorkflowState.WAITING,
    )
    with pytest.raises(OrderRuleViolation):
        transition_target(order, TransitionTrigger.CHECKOUT_READY)


def test_reservation_failure_rejects_without_a_payment():
    order = replace(
        BASE,
        status=OrderStatus.PROCESSING,
        stock_step=StockStep.RESERVE_FAILED,
        payment_status=None,
        workflow_phase=WorkflowPhase.CHECKOUT,
        workflow_state=WorkflowState.WAITING,
    )
    assert transition_target(order, TransitionTrigger.RESERVATION_FAILED) == OrderStatus.REJECTED
    with pytest.raises(OrderRuleViolation):
        transition_target(
            replace(order, payment_status=PaymentStatus.PENDING),
            TransitionTrigger.RESERVATION_FAILED,
        )


def test_definite_payment_failure_starts_compensation_instead_of_ending_immediately():
    order = replace(
        BASE,
        status=OrderStatus.PROCESSING,
        payment_method=PaymentMethod.SIMULATED,
        payment_status=PaymentStatus.FAILED,
        workflow_phase=WorkflowPhase.CHECKOUT,
        workflow_state=WorkflowState.WAITING,
    )
    assert transition_target(order, TransitionTrigger.PAYMENT_FAILED) == OrderStatus.CANCELLING
    with pytest.raises(OrderRuleViolation):
        transition_target(
            replace(order, payment_status=PaymentStatus.PENDING), TransitionTrigger.PAYMENT_FAILED
        )


def test_confirm_and_cancel_reuse_action_guards():
    assert transition_target(BASE, TransitionTrigger.CONFIRM, actor=ADMIN) == OrderStatus.PREPARING
    assert (
        transition_target(BASE, TransitionTrigger.CANCEL, actor=CUSTOMER) == OrderStatus.CANCELLING
    )
    with pytest.raises(OrderRuleViolation, match="AUTH_REQUIRED"):
        transition_target(BASE, TransitionTrigger.CANCEL)
    with pytest.raises(OrderRuleViolation, match="FORBIDDEN"):
        transition_target(BASE, TransitionTrigger.CONFIRM, actor=CUSTOMER)


def test_shipping_requires_a_committed_result_for_an_active_dispatch():
    order = replace(
        BASE,
        status=OrderStatus.PREPARING,
        stock_step=StockStep.COMMITTED,
        workflow_phase=WorkflowPhase.DISPATCH,
        workflow_state=WorkflowState.WAITING,
    )
    assert transition_target(order, TransitionTrigger.STOCK_COMMITTED) == OrderStatus.SHIPPING
    for changes in (
        {"stock_step": StockStep.COMMIT_PENDING},
        {"workflow_phase": WorkflowPhase.IDLE},
    ):
        with pytest.raises(OrderRuleViolation):
            transition_target(replace(order, **changes), TransitionTrigger.STOCK_COMMITTED)


@pytest.mark.parametrize(
    "method,phase",
    [
        (PaymentMethod.COD, WorkflowPhase.COMPLETION),
        (PaymentMethod.SIMULATED, WorkflowPhase.IDLE),
    ],
)
def test_completion_requires_delivery_and_verified_payment(method, phase):
    order = replace(
        BASE,
        status=OrderStatus.SHIPPING,
        stock_step=StockStep.COMMITTED,
        payment_method=method,
        payment_status=PaymentStatus.SUCCEEDED,
        workflow_phase=phase,
        workflow_state=WorkflowState.DONE if phase == WorkflowPhase.IDLE else WorkflowState.WAITING,
    )
    assert (
        transition_target(order, TransitionTrigger.DELIVERY_COMPLETED, delivered=True)
        == OrderStatus.COMPLETED
    )
    for delivered in (False, 1):
        with pytest.raises(OrderRuleViolation):
            transition_target(order, TransitionTrigger.DELIVERY_COMPLETED, delivered=delivered)
    with pytest.raises(OrderRuleViolation):
        transition_target(
            replace(order, payment_status=PaymentStatus.AWAITING_COLLECTION),
            TransitionTrigger.DELIVERY_COMPLETED,
            delivered=True,
        )


@pytest.mark.parametrize(
    "method,payment",
    [
        (PaymentMethod.COD, PaymentStatus.CANCELLED),
        (PaymentMethod.SIMULATED, PaymentStatus.REFUNDED),
        (PaymentMethod.SIMULATED, PaymentStatus.FAILED),
    ],
)
def test_cancellation_requires_both_branches_and_allows_valid_recovery(method, payment):
    order = replace(
        BASE,
        status=OrderStatus.CANCELLING,
        stock_step=StockStep.RELEASED,
        payment_method=method,
        payment_status=payment,
        workflow_phase=WorkflowPhase.CANCELLATION,
        workflow_state=WorkflowState.NEEDS_ATTENTION,
    )
    assert (
        transition_target(order, TransitionTrigger.CANCELLATION_COMPLETED) == OrderStatus.CANCELLED
    )
    for changes in (
        {"stock_step": StockStep.RELEASE_PENDING},
        {"payment_status": PaymentStatus.REFUND_PENDING},
    ):
        with pytest.raises(OrderRuleViolation):
            transition_target(replace(order, **changes), TransitionTrigger.CANCELLATION_COMPLETED)


@pytest.mark.parametrize(
    "status", [OrderStatus.REJECTED, OrderStatus.CANCELLED, OrderStatus.COMPLETED]
)
def test_no_event_can_resurrect_a_terminal_order(status):
    for trigger in TransitionTrigger:
        with pytest.raises(OrderRuleViolation):
            transition_target(replace(BASE, status=status), trigger, actor=ADMIN, delivered=True)
