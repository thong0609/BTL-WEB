"""Apply payment commands and settle delayed demo results in one local transaction."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from commerce_backend_common.messaging import MessageEnvelope
from commerce_payment.contracts import (
    CancelCodPayment,
    Command,
    InitializeCodPayment,
    PaymentMessageError,
    ProcessPayment,
    RecordCodCollection,
    RefundPayment,
    command_hash,
    parse_command,
    payload_hash,
)
from commerce_payment.models import (
    DemoConfiguration,
    OutboxMessage,
    PaymentAttempt,
    PaymentStatusHistory,
    ProcessedMessage,
    RefundAttempt,
)

COMMAND_CONSUMER = "payment.commands"
OPERATION_CONSUMER = "payment.operation"
SIMULATION_FAILURE = "SIMULATION_FAILURE"
_EVENTS = {
    "PaymentInitialized": "payment.initialized",
    "PaymentSucceeded": "payment.succeeded",
    "PaymentFailed": "payment.failed",
    "CodCollected": "payment.cod-collected",
    "CodPaymentCancelled": "payment.cod-cancelled",
    "PaymentRefunded": "payment.refunded",
    "PaymentRefundFailed": "payment.refund-failed",
    "PaymentCommandRejected": "payment.command-rejected",
}


class PaymentHandleResult:
    def __init__(
        self,
        disposition: Literal["applied", "replayed", "rejected"],
        payment_id: UUID | None = None,
        event_type: str | None = None,
    ) -> None:
        self.disposition = disposition
        self.payment_id = payment_id
        self.event_type = event_type


async def handle_message(
    session: AsyncSession, envelope: MessageEnvelope, *, now: datetime | None = None
) -> PaymentHandleResult:
    command = parse_command(envelope)
    async with session.begin():
        return await _handle(session, envelope, command, now or datetime.now(UTC))


async def settle_due(session: AsyncSession, *, now: datetime | None = None) -> int:
    async with session.begin():
        return await _settle(session, now or datetime.now(UTC))


async def _handle(
    session: AsyncSession, envelope: MessageEnvelope, command: Command, now: datetime
) -> PaymentHandleResult:
    transport = await _claim(
        session,
        consumer=COMMAND_CONSUMER,
        message_id=envelope.message_id,
        message_type=envelope.message_type,
        message_version=envelope.version,
        digest=payload_hash(envelope.payload),
        correlation_id=envelope.correlation_id,
        now=now,
    )
    if transport == "same":
        return await _replay_result(session, command)
    if transport == "different":
        raise PaymentMessageError("PAYLOAD_MISMATCH")
    operation = await _claim(
        session,
        consumer=OPERATION_CONSUMER,
        message_id=command.operation_id,
        message_type=type(command).__name__,
        message_version=envelope.version,
        digest=command_hash(command),
        correlation_id=envelope.correlation_id,
        now=now,
    )
    if operation == "same":
        return await _replay_result(session, command)
    if operation == "different":
        if await _rejection_recorded(session, command.operation_id):
            return await _replay_result(session, command)
        payment = await _payment_for_operation(session, command.operation_id)
        return _reject(session, envelope, command, "OPERATION_CONFLICT", payment, now)
    if isinstance(command, InitializeCodPayment):
        return await _initialize(session, envelope, command, now)
    if isinstance(command, ProcessPayment):
        return await _process(session, envelope, command, now)
    if isinstance(command, RecordCodCollection):
        return await _collect(session, envelope, command, now)
    if isinstance(command, CancelCodPayment):
        return await _cancel(session, envelope, command, now)
    return await _refund(session, envelope, command, now)


async def _claim(
    session: AsyncSession,
    *,
    consumer: str,
    message_id: UUID,
    message_type: str,
    message_version: int,
    digest: str,
    correlation_id: UUID,
    now: datetime,
) -> Literal["inserted", "same", "different"]:
    inserted = await session.scalar(
        pg_insert(ProcessedMessage)
        .values(
            consumer_name=consumer,
            message_id=message_id,
            message_type=message_type,
            message_version=message_version,
            payload_hash=digest,
            correlation_id=correlation_id,
            processed_at=now,
        )
        .on_conflict_do_nothing(index_elements=["consumer_name", "message_id"])
        .returning(ProcessedMessage.message_id)
    )
    if inserted is not None:
        return "inserted"
    existing = await session.get(ProcessedMessage, (consumer, message_id))
    if existing is None or existing.payload_hash != digest:
        return "different"
    return "same"


async def _replay_result(session: AsyncSession, command: Command) -> PaymentHandleResult:
    rows = (
        await session.scalars(
            select(OutboxMessage)
            .where(OutboxMessage.payload["operationId"].as_string() == str(command.operation_id))
            .order_by(OutboxMessage.created_at.desc())
        )
    ).all()
    payment = await _payment_for_operation(session, command.operation_id)

    for row in rows:
        if row.message_type == "PaymentCommandRejected":
            payment_id = payment.id if payment is not None else None
            if row.payload.get("paymentId"):
                payment_id = UUID(str(row.payload["paymentId"]))
            return PaymentHandleResult("rejected", payment_id, row.message_type)
        if row.message_type in _EVENTS:
            payment_id = payment.id if payment is not None else None
            if row.payload.get("paymentId"):
                payment_id = UUID(str(row.payload["paymentId"]))
            return PaymentHandleResult("replayed", payment_id, row.message_type)

    if payment is not None:
        return PaymentHandleResult("replayed", payment.id, None)
    refund = await session.scalar(
        select(RefundAttempt).where(RefundAttempt.operation_id == command.operation_id)
    )
    if refund is not None:
        linked = await session.get(PaymentAttempt, refund.payment_id)
        return PaymentHandleResult("replayed", None if linked is None else linked.id, None)
    return PaymentHandleResult("replayed")


async def _rejection_recorded(session: AsyncSession, operation_id: UUID) -> bool:
    found = await session.scalar(
        select(OutboxMessage.id).where(
            OutboxMessage.message_type == "PaymentCommandRejected",
            OutboxMessage.payload["operationId"].as_string() == str(operation_id),
        )
    )
    return found is not None


async def _payment_for_operation(
    session: AsyncSession, operation_id: UUID
) -> PaymentAttempt | None:
    payment = await session.scalar(
        select(PaymentAttempt)
        .where(
            or_(
                PaymentAttempt.operation_id == operation_id,
                PaymentAttempt.collection_operation_id == operation_id,
                PaymentAttempt.cancel_operation_id == operation_id,
            )
        )
        .with_for_update()
    )
    if payment is not None:
        return payment
    refund = await session.scalar(
        select(RefundAttempt).where(RefundAttempt.operation_id == operation_id)
    )
    if refund is None:
        return None
    return await session.get(PaymentAttempt, refund.payment_id, with_for_update=True)


async def _initialize(
    session: AsyncSession,
    envelope: MessageEnvelope,
    command: InitializeCodPayment,
    now: datetime,
) -> PaymentHandleResult:
    existing = await _lock_order(session, command.order_id)
    if existing is not None:
        return _reject(session, envelope, command, "PAYMENT_ALREADY_EXISTS", existing, now)
    payment = _new_payment(command, "COD", None, "AWAITING_COLLECTION", now)
    session.add(payment)
    await session.flush()
    _history(session, payment, None, command.operation_id, envelope, now, None, "SYSTEM", None)
    _emit(
        session,
        "PaymentInitialized",
        payment,
        command.operation_id,
        envelope,
        now,
        {"method": "COD", "amount": str(payment.amount), "currency": payment.currency},
    )
    return PaymentHandleResult("applied", payment.id, "PaymentInitialized")


async def _process(
    session: AsyncSession,
    envelope: MessageEnvelope,
    command: ProcessPayment,
    now: datetime,
) -> PaymentHandleResult:
    existing = await _lock_order(session, command.order_id)
    if existing is not None:
        return _reject(session, envelope, command, "PAYMENT_ALREADY_EXISTS", existing, now)
    config = await _demo(session)
    scenario = config.payment_scenario
    if scenario == "SUCCESS":
        payment = _new_payment(command, "SIMULATED", scenario, "SUCCEEDED", now)
        payment.succeeded_at = now
    elif scenario == "FAILURE":
        payment = _new_payment(command, "SIMULATED", scenario, "FAILED", now)
        payment.failed_at = now
        payment.failure_code = SIMULATION_FAILURE
    elif scenario in {"DELAYED_SUCCESS", "DELAYED_FAILURE"}:
        payment = _new_payment(command, "SIMULATED", scenario, "PENDING", now)
        payment.resolve_after = now + timedelta(seconds=config.delay_seconds)
    else:
        raise PaymentMessageError("DEMO_CONFIGURATION_INVALID")
    session.add(payment)
    await session.flush()
    _history(
        session,
        payment,
        None,
        command.operation_id,
        envelope,
        now,
        payment.failure_code,
        "SYSTEM",
        None,
    )
    if payment.status == "PENDING":
        return PaymentHandleResult("applied", payment.id, None)
    event = "PaymentSucceeded" if payment.status == "SUCCEEDED" else "PaymentFailed"
    extra: dict[str, Any] = {"amount": str(payment.amount), "currency": payment.currency}
    if event == "PaymentSucceeded":
        extra["method"] = "SIMULATED"
    else:
        extra["code"] = SIMULATION_FAILURE
    _emit(session, event, payment, command.operation_id, envelope, now, extra)
    return PaymentHandleResult("applied", payment.id, event)


async def _collect(
    session: AsyncSession,
    envelope: MessageEnvelope,
    command: RecordCodCollection,
    now: datetime,
) -> PaymentHandleResult:
    payment = await _lock_payment(session, command.payment_id)
    if payment is None:
        return _reject(session, envelope, command, "PAYMENT_NOT_FOUND", None, now)
    if payment.order_id != command.order_id or payment.method != "COD":
        return _reject(session, envelope, command, "PAYMENT_STATE_CONFLICT", payment, now)
    if payment.status != "AWAITING_COLLECTION":
        return _reject(session, envelope, command, "PAYMENT_STATE_CONFLICT", payment, now)
    previous = payment.status
    payment.status = "SUCCEEDED"
    payment.version += 1
    payment.collection_operation_id = command.operation_id
    payment.collected_by = command.collected_by
    payment.succeeded_at = now
    payment.updated_at = now
    _history(
        session,
        payment,
        previous,
        command.operation_id,
        envelope,
        now,
        None,
        "ADMIN",
        command.collected_by,
    )
    _emit(
        session,
        "CodCollected",
        payment,
        command.operation_id,
        envelope,
        now,
        {
            "amount": str(payment.amount),
            "currency": payment.currency,
            "collectedBy": str(command.collected_by),
        },
    )
    return PaymentHandleResult("applied", payment.id, "CodCollected")


async def _cancel(
    session: AsyncSession,
    envelope: MessageEnvelope,
    command: CancelCodPayment,
    now: datetime,
) -> PaymentHandleResult:
    payment = await _lock_payment(session, command.payment_id)
    if payment is None:
        return _reject(session, envelope, command, "PAYMENT_NOT_FOUND", None, now)
    if (
        payment.order_id != command.order_id
        or payment.method != "COD"
        or payment.status != "AWAITING_COLLECTION"
    ):
        return _reject(session, envelope, command, "PAYMENT_STATE_CONFLICT", payment, now)
    previous = payment.status
    payment.status = "CANCELLED"
    payment.version += 1
    payment.cancel_operation_id = command.operation_id
    payment.cancelled_at = now
    payment.updated_at = now
    _history(
        session,
        payment,
        previous,
        command.operation_id,
        envelope,
        now,
        command.reason,
        "SYSTEM",
        None,
    )
    _emit(
        session,
        "CodPaymentCancelled",
        payment,
        command.operation_id,
        envelope,
        now,
        {"amount": str(payment.amount), "currency": payment.currency},
    )
    return PaymentHandleResult("applied", payment.id, "CodPaymentCancelled")


async def _refund(
    session: AsyncSession,
    envelope: MessageEnvelope,
    command: RefundPayment,
    now: datetime,
) -> PaymentHandleResult:
    payment = await _lock_payment(session, command.payment_id)
    if payment is None:
        return _reject(session, envelope, command, "PAYMENT_NOT_FOUND", None, now)
    if payment.order_id != command.order_id:
        return _reject(session, envelope, command, "PAYMENT_STATE_CONFLICT", payment, now)
    if command.amount != payment.amount or command.currency != payment.currency:
        return _reject(session, envelope, command, "AMOUNT_MISMATCH", payment, now)
    if payment.method != "SIMULATED" or payment.status != "SUCCEEDED":
        return _reject(session, envelope, command, "PAYMENT_STATE_CONFLICT", payment, now)
    config = await _demo(session)
    scenario = config.refund_scenario
    if scenario not in {"SUCCESS", "DELAYED_SUCCESS", "FAIL_UNTIL_RETRY"}:
        raise PaymentMessageError("DEMO_CONFIGURATION_INVALID")
    previous = payment.status
    refund = RefundAttempt(
        id=uuid4(),
        payment_id=payment.id,
        operation_id=command.operation_id,
        request_hash=command_hash(command),
        amount=command.amount,
        currency=command.currency,
        status="PENDING",
        reason=command.reason,
        simulation_scenario=scenario,
        retry_count=0,
        next_retry_at=None,
        last_error_code=None,
        version=1,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )
    if scenario == "SUCCESS":
        payment.status = "REFUNDED"
        refund.status = "SUCCEEDED"
        refund.completed_at = now
    else:
        payment.status = "REFUND_PENDING"
        refund.next_retry_at = now + timedelta(seconds=config.delay_seconds)
        if scenario == "FAIL_UNTIL_RETRY":
            refund.retry_count = 1
            refund.last_error_code = SIMULATION_FAILURE
    payment.version += 1
    payment.updated_at = now
    session.add(refund)
    await session.flush()
    _history(
        session,
        payment,
        previous,
        command.operation_id,
        envelope,
        now,
        command.reason,
        "SYSTEM",
        None,
    )
    _refund_history(session, payment, refund, None, envelope, now, command.reason)
    if scenario == "FAIL_UNTIL_RETRY":
        _emit_refund(
            session,
            "PaymentRefundFailed",
            payment,
            refund,
            command.operation_id,
            envelope,
            now,
            {"refundId": str(refund.id), "code": SIMULATION_FAILURE, "retryable": True},
        )
        return PaymentHandleResult("applied", payment.id, "PaymentRefundFailed")
    if scenario == "DELAYED_SUCCESS":
        return PaymentHandleResult("applied", payment.id, None)
    _emit_refund(
        session,
        "PaymentRefunded",
        payment,
        refund,
        command.operation_id,
        envelope,
        now,
        {"refundId": str(refund.id), "amount": str(refund.amount), "currency": refund.currency},
    )
    return PaymentHandleResult("applied", payment.id, "PaymentRefunded")


async def _settle(session: AsyncSession, now: datetime) -> int:
    finished = 0
    pending = (
        await session.scalars(
            select(PaymentAttempt)
            .where(PaymentAttempt.status == "PENDING", PaymentAttempt.resolve_after <= now)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for payment in pending:
        if payment.simulation_scenario not in {"DELAYED_SUCCESS", "DELAYED_FAILURE"}:
            raise PaymentMessageError("DEMO_CONFIGURATION_INVALID")
        success = payment.simulation_scenario == "DELAYED_SUCCESS"
        previous = payment.status
        message_id = await _origin_message(session, payment.id, None)
        correlation_id, causation_id = await _origin(session, message_id)
        payment.resolve_after = None
        payment.updated_at = now
        payment.version += 1
        if success:
            payment.status = "SUCCEEDED"
            payment.succeeded_at = now
            event = "PaymentSucceeded"
            extra: dict[str, Any] = {
                "method": "SIMULATED",
                "amount": str(payment.amount),
                "currency": payment.currency,
            }
        else:
            payment.status = "FAILED"
            payment.failed_at = now
            payment.failure_code = SIMULATION_FAILURE
            event = "PaymentFailed"
            extra = {
                "amount": str(payment.amount),
                "currency": payment.currency,
                "code": SIMULATION_FAILURE,
            }
        _history_row(
            session,
            payment,
            None,
            "PAYMENT",
            previous,
            payment.operation_id,
            message_id,
            now,
            payment.failure_code,
            "SYSTEM",
            None,
        )
        _queue(
            session,
            event,
            "PAYMENT",
            payment.id,
            payment.version,
            payment.order_id,
            payment,
            payment.operation_id,
            correlation_id,
            causation_id,
            now,
            extra,
        )
        finished += 1
    waiting = (
        await session.scalars(
            select(PaymentAttempt)
            .where(PaymentAttempt.status == "REFUND_PENDING")
            .with_for_update(skip_locked=True)
        )
    ).all()
    for payment in waiting:
        refund = await session.scalar(
            select(RefundAttempt)
            .where(
                RefundAttempt.payment_id == payment.id,
                RefundAttempt.status == "PENDING",
                RefundAttempt.next_retry_at.is_not(None),
                RefundAttempt.next_retry_at <= now,
            )
            .with_for_update()
        )
        if refund is None:
            continue
        if refund.simulation_scenario == "FAIL_UNTIL_RETRY" and refund.retry_count < 1:
            continue
        if refund.simulation_scenario not in {"DELAYED_SUCCESS", "FAIL_UNTIL_RETRY"}:
            continue
        previous_payment = payment.status
        previous_refund = refund.status
        message_id = await _origin_message(session, payment.id, refund.id)
        correlation_id, causation_id = await _origin(session, message_id)
        payment.status = "REFUNDED"
        payment.version += 1
        payment.updated_at = now
        refund.status = "SUCCEEDED"
        refund.version += 1
        refund.completed_at = now
        refund.updated_at = now
        refund.next_retry_at = None
        _history_row(
            session,
            payment,
            None,
            "PAYMENT",
            previous_payment,
            refund.operation_id,
            message_id,
            now,
            None,
            "SYSTEM",
            None,
        )
        _history_row(
            session,
            payment,
            refund,
            "REFUND",
            previous_refund,
            refund.operation_id,
            message_id,
            now,
            None,
            "SYSTEM",
            None,
        )
        _queue(
            session,
            "PaymentRefunded",
            "REFUND",
            refund.id,
            payment.version,
            payment.order_id,
            payment,
            refund.operation_id,
            correlation_id,
            causation_id,
            now,
            {"refundId": str(refund.id), "amount": str(refund.amount), "currency": refund.currency},
        )
        finished += 1
    return finished


def _new_payment(
    command: InitializeCodPayment | ProcessPayment,
    method: str,
    scenario: str | None,
    status: str,
    now: datetime,
) -> PaymentAttempt:
    return PaymentAttempt(
        id=uuid4(),
        order_id=command.order_id,
        customer_id=command.customer_id,
        operation_id=command.operation_id,
        request_hash=command_hash(command),
        method=method,
        amount=command.amount,
        currency=command.currency,
        status=status,
        simulation_scenario=scenario,
        resolve_after=None,
        failure_code=None,
        collection_operation_id=None,
        cancel_operation_id=None,
        collected_by=None,
        version=1,
        created_at=now,
        updated_at=now,
        succeeded_at=None,
        failed_at=None,
        cancelled_at=None,
    )


async def _lock_order(session: AsyncSession, order_id: UUID) -> PaymentAttempt | None:
    return await session.scalar(
        select(PaymentAttempt).where(PaymentAttempt.order_id == order_id).with_for_update()
    )


async def _lock_payment(session: AsyncSession, payment_id: UUID) -> PaymentAttempt | None:
    return await session.scalar(
        select(PaymentAttempt).where(PaymentAttempt.id == payment_id).with_for_update()
    )


async def _demo(session: AsyncSession) -> DemoConfiguration:
    config = await session.scalar(
        select(DemoConfiguration).where(DemoConfiguration.id == 1).with_for_update(read=True)
    )
    if config is None:
        raise PaymentMessageError("DEMO_CONFIGURATION_MISSING")
    return config


def _history(
    session: AsyncSession,
    payment: PaymentAttempt,
    previous: str | None,
    operation_id: UUID,
    envelope: MessageEnvelope,
    now: datetime,
    reason: str | None,
    actor_type: str,
    actor_id: UUID | None,
) -> None:
    _history_row(
        session,
        payment,
        None,
        "PAYMENT",
        previous,
        operation_id,
        envelope.message_id,
        now,
        reason,
        actor_type,
        actor_id,
    )


def _refund_history(
    session: AsyncSession,
    payment: PaymentAttempt,
    refund: RefundAttempt,
    previous: str | None,
    envelope: MessageEnvelope,
    now: datetime,
    reason: str | None,
) -> None:
    _history_row(
        session,
        payment,
        refund,
        "REFUND",
        previous,
        refund.operation_id,
        envelope.message_id,
        now,
        reason,
        "SYSTEM",
        None,
    )


def _history_row(
    session: AsyncSession,
    payment: PaymentAttempt,
    refund: RefundAttempt | None,
    entity_type: str,
    previous: str | None,
    operation_id: UUID,
    message_id: UUID | None,
    now: datetime,
    reason: str | None,
    actor_type: str,
    actor_id: UUID | None,
) -> None:
    session.add(
        PaymentStatusHistory(
            id=uuid4(),
            payment_id=payment.id,
            refund_id=None if refund is None else refund.id,
            entity_type=entity_type,
            from_status=previous,
            to_status=payment.status if refund is None else refund.status,
            operation_id=operation_id,
            message_id=message_id,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            created_at=now,
        )
    )


def _emit(
    session: AsyncSession,
    event_type: str,
    payment: PaymentAttempt,
    operation_id: UUID,
    envelope: MessageEnvelope,
    now: datetime,
    extra: dict[str, Any],
) -> None:
    _queue(
        session,
        event_type,
        "PAYMENT",
        payment.id,
        payment.version,
        payment.order_id,
        payment,
        operation_id,
        envelope.correlation_id,
        envelope.message_id,
        now,
        extra,
    )


def _emit_refund(
    session: AsyncSession,
    event_type: str,
    payment: PaymentAttempt,
    refund: RefundAttempt,
    operation_id: UUID,
    envelope: MessageEnvelope,
    now: datetime,
    extra: dict[str, Any],
) -> None:
    _queue(
        session,
        event_type,
        "REFUND",
        refund.id,
        payment.version,
        payment.order_id,
        payment,
        operation_id,
        envelope.correlation_id,
        envelope.message_id,
        now,
        extra,
    )


def _queue(
    session: AsyncSession,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    aggregate_version: int | None,
    order_id: UUID,
    payment: PaymentAttempt | None,
    operation_id: UUID,
    correlation_id: UUID,
    causation_id: UUID | None,
    now: datetime,
    extra: dict[str, Any],
) -> None:
    payload: dict[str, Any] = {
        "orderId": str(order_id),
        "operationId": str(operation_id),
        "paymentId": None if payment is None else str(payment.id),
        "paymentVersion": None if payment is None else payment.version,
        "paymentStatus": None if payment is None else payment.status,
    }
    payload.update(extra)
    session.add(
        OutboxMessage(
            id=uuid4(),
            message_type=event_type,
            message_version=1,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            exchange_name="commerce.events",
            routing_key=_EVENTS[event_type],
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=payload,
            status="PENDING",
            attempt_count=0,
            next_attempt_at=now,
            locked_by=None,
            locked_until=None,
            last_error=None,
            created_at=now,
            published_at=None,
        )
    )


def _reject(
    session: AsyncSession,
    envelope: MessageEnvelope,
    command: Command,
    code: str,
    payment: PaymentAttempt | None,
    now: datetime,
) -> PaymentHandleResult:
    _queue(
        session,
        "PaymentCommandRejected",
        "PAYMENT",
        command.operation_id if payment is None else payment.id,
        None if payment is None else payment.version,
        command.order_id,
        payment,
        command.operation_id,
        envelope.correlation_id,
        envelope.message_id,
        now,
        {"rejectedType": type(command).__name__, "code": code},
    )
    return PaymentHandleResult(
        "rejected", None if payment is None else payment.id, "PaymentCommandRejected"
    )


async def _origin_message(session: AsyncSession, payment_id: UUID, refund_id: UUID | None) -> UUID:
    message_id = await session.scalar(
        select(PaymentStatusHistory.message_id).where(
            PaymentStatusHistory.payment_id == payment_id,
            PaymentStatusHistory.refund_id == refund_id
            if refund_id is not None
            else PaymentStatusHistory.refund_id.is_(None),
            PaymentStatusHistory.from_status.is_(None),
        )
    )
    if message_id is None:
        raise PaymentMessageError("COMMAND_CONTEXT_MISSING")
    return message_id


async def _origin(session: AsyncSession, message_id: UUID) -> tuple[UUID, UUID]:
    row = await session.get(ProcessedMessage, (COMMAND_CONSUMER, message_id))
    if row is None:
        raise PaymentMessageError("COMMAND_CONTEXT_MISSING")
    return row.correlation_id, message_id
