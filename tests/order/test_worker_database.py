import asyncio
import copy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from commerce_backend_common.messaging import MessageEnvelope, PublishUnconfirmed
from commerce_order.api.schemas import CreateOrder, Quote
from commerce_order.domain.enums import (
    ActorRole,
    OrderStatus,
    PaymentStatus,
    PaymentStep,
    StockStep,
    WorkflowPhase,
    WorkflowState,
)
from commerce_order.domain.transitions import Actor
from commerce_order.messaging.handlers import EventHandlers
from commerce_order.messaging.inbox import InboxProcessor
from commerce_order.messaging.outbox import OutboxPublisher
from commerce_order.messaging.schemas import (
    COMMANDS,
    EVENTS,
    EventRetryable,
    MessageInvalid,
    decode_event,
)
from commerce_order.models import (
    OrderRecord,
    OrderWorkflow,
    OutboxMessage,
    ProcessedMessage,
)
from commerce_order.models.messaging import OutboxStatus
from commerce_order.repositories.messaging import OutboxRepository
from commerce_order.services.persistence import OrderPersistence
from commerce_order.settings import Settings

pytestmark = pytest.mark.integration
ACTOR = Actor(UUID("10000000-0000-4000-8000-000000000001"), ActorRole.CUSTOMER)


async def create(store, payload, quote):
    async def loader():
        return Quote.model_validate(quote)

    result = await OrderPersistence(store["sessions"]).accept_order(
        ACTOR, uuid4().hex, CreateOrder.model_validate(payload), loader
    )
    async with store["sessions"]() as session:
        command = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.aggregate_id == UUID(result.body["orderId"]))
        )
    return command


def response(command, kind, **values):
    envelope = MessageEnvelope(
        message_id=uuid4(),
        message_type=kind,
        version=1,
        correlation_id=command.correlation_id,
        causation_id=command.id,
        occurred_at="2026-11-15T00:00:00Z",
        payload={
            "orderId": str(command.aggregate_id),
            "operationId": command.payload["operationId"],
            **values,
        },
    )
    return decode_event(envelope.model_dump_json().encode(), EVENTS[kind][0])


async def reserve(store, payload, quote):
    command = await create(store, payload, quote)
    event = response(
        command, "StockReserved", reservationId=str(uuid4()), items=command.payload["items"]
    )
    await InboxProcessor(store["sessions"]).process(event)
    async with store["sessions"]() as session:
        payment = await session.scalar(
            select(OutboxMessage).where(
                OutboxMessage.aggregate_id == command.aggregate_id,
                OutboxMessage.message_type.in_(["InitializeCodPayment", "ProcessPayment"]),
            )
        )
    return command, payment, event


async def due(store):
    async with store["sessions"]() as session, session.begin():
        await session.execute(
            update(OutboxMessage).values(
                next_attempt_at=func.clock_timestamp() - timedelta(seconds=1)
            )
        )


def test_outbox_claims_are_exclusive_and_expired_owner_cannot_finish(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        command = await create(order_runtime_store, create_payload, quote_payload)
        repository = OutboxRepository(order_runtime_store["sessions"])
        first, second = await asyncio.gather(
            repository.claim(10, 60, 10), repository.claim(10, 60, 10)
        )
        assert sorted([len(first), len(second)]) == [0, 1]
        original = (first or second)[0]
        async with order_runtime_store["sessions"]() as session, session.begin():
            await session.execute(
                update(OutboxMessage)
                .where(OutboxMessage.id == command.id)
                .values(locked_until=func.clock_timestamp() - timedelta(seconds=1))
            )
        takeover = (await repository.claim(10, 60, 10))[0]
        assert takeover.token != original.token
        assert takeover.message == original.message
        assert not await repository.published(original)
        assert await repository.published(takeover)
        assert await repository.claim(10, 60, 10) == []

    asyncio.run(exercise())


def test_unconfirmed_publish_retries_exact_envelope_outside_transaction(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        command = await create(order_runtime_store, create_payload, quote_payload)
        seen = []

        class Sender:
            async def publish(self, exchange_name, routing_key, envelope):
                # A separate connection can lock this row while network publication runs.
                async with order_runtime_store["sessions"]() as session, session.begin():
                    await session.scalar(
                        select(OutboxMessage)
                        .where(OutboxMessage.id == command.id)
                        .with_for_update(nowait=True)
                    )
                seen.append(envelope)
                if len(seen) == 1:
                    raise PublishUnconfirmed("outcome unknown")

        repository = OutboxRepository(order_runtime_store["sessions"])
        publisher = OutboxPublisher(repository, Sender(), Settings(app_env="test"))
        assert await publisher.once() == 0
        async with order_runtime_store["sessions"]() as session:
            row = await session.get(OutboxMessage, command.id)
            assert row.status == OutboxStatus.PENDING and row.published_at is None
        await due(order_runtime_store)
        assert await publisher.once() == 1
        assert seen[0] == seen[1] and seen[0].message_id == command.id
        assert seen[0].occurred_at == command.created_at

    asyncio.run(exercise())


def test_exhausted_and_invalid_outbox_need_attention(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        command = await create(order_runtime_store, create_payload, quote_payload)

        class Failing:
            async def publish(self, *args):
                raise PublishUnconfirmed("private connection")

        publisher = OutboxPublisher(
            OutboxRepository(order_runtime_store["sessions"]),
            Failing(),
            Settings(app_env="test", order_outbox_max_attempts=1),
        )
        assert await publisher.once() == 0
        assert await publisher.once() == 0
        async with order_runtime_store["sessions"]() as session:
            row = await session.get(OutboxMessage, command.id)
            assert row.status == OutboxStatus.NEEDS_ATTENTION and row.attempt_count == 1
            assert "private" not in row.last_error
        other = await create(order_runtime_store, create_payload, quote_payload)
        async with order_runtime_store["sessions"]() as session, session.begin():
            row = await session.get(OutboxMessage, other.id)
            row.message_version = 2
        assert await publisher.once() == 0
        async with order_runtime_store["sessions"]() as session:
            row = await session.get(OutboxMessage, other.id)
            assert (
                row.status == OutboxStatus.NEEDS_ATTENTION
                and row.last_error == "OUTBOX_ENVELOPE_INVALID"
            )

    asyncio.run(exercise())


def test_inbox_concurrent_duplicate_different_id_same_operation_and_conflict(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        command = await create(order_runtime_store, create_payload, quote_payload)
        event = response(
            command, "StockReserved", reservationId=str(uuid4()), items=command.payload["items"]
        )
        processor = InboxProcessor(order_runtime_store["sessions"])
        results = await asyncio.gather(processor.process(event), processor.process(event))
        assert sorted(results) == ["applied", "duplicate"]
        another = event.envelope.model_copy(update={"message_id": uuid4()})
        assert (
            await processor.process(
                decode_event(another.model_dump_json().encode(), EVENTS["StockReserved"][0])
            )
            == "ignored"
        )
        changed = event.envelope.model_dump(mode="json")
        changed["payload"]["items"][0]["quantity"] += 1
        with pytest.raises(MessageInvalid, match="MESSAGE_ID_CONFLICT"):
            import json

            await processor.process(
                decode_event(json.dumps(changed).encode(), EVENTS["StockReserved"][0])
            )
        async with order_runtime_store["sessions"]() as session:
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 2
            assert await session.scalar(select(func.count()).select_from(ProcessedMessage)) == 2
            order = await session.get(OrderRecord, command.aggregate_id)
            assert order.status == OrderStatus.PROCESSING and order.version == 1

    asyncio.run(exercise())


def test_inbox_rollback_includes_workflow_outbox_and_receipt(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        command = await create(order_runtime_store, create_payload, quote_payload)
        event = response(
            command, "StockReserved", reservationId=str(uuid4()), items=command.payload["items"]
        )

        class Interrupted(EventHandlers):
            async def apply(self, session, locked, event):
                await super().apply(session, locked, event)
                await session.flush()
                raise RuntimeError("simulated crash before commit")

        with pytest.raises(RuntimeError):
            await InboxProcessor(order_runtime_store["sessions"], Interrupted()).process(event)
        async with order_runtime_store["sessions"]() as session:
            assert await session.scalar(select(func.count()).select_from(ProcessedMessage)) == 0
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 1
            flow = await session.get(OrderWorkflow, command.aggregate_id)
            assert flow.reservation_id is None and flow.payment_operation_id is None
        assert await InboxProcessor(order_runtime_store["sessions"]).process(event) == "applied"

    asyncio.run(exercise())


@pytest.mark.parametrize("bad", ["operation", "correlation", "causation", "items", "reservation"])
def test_bad_identity_does_not_change_order_or_write_inbox(
    order_runtime_store, create_payload, quote_payload, bad
):
    async def exercise():
        command = await create(order_runtime_store, create_payload, quote_payload)
        event = response(
            command, "StockReserved", reservationId=str(uuid4()), items=command.payload["items"]
        )
        raw = event.envelope.model_dump(mode="json")
        if bad == "operation":
            raw["payload"]["operationId"] = str(uuid4())
        elif bad == "correlation":
            raw["correlationId"] = str(uuid4())
        elif bad == "causation":
            raw["causationId"] = str(uuid4())
        elif bad == "items":
            raw["payload"]["items"][0]["quantity"] += 1
        else:
            async with order_runtime_store["sessions"]() as session, session.begin():
                flow = await session.get(OrderWorkflow, command.aggregate_id)
                flow.reservation_id = uuid4()
        import json

        with pytest.raises(MessageInvalid):
            await InboxProcessor(order_runtime_store["sessions"]).process(
                decode_event(json.dumps(raw).encode(), EVENTS["StockReserved"][0])
            )
        async with order_runtime_store["sessions"]() as session:
            assert await session.scalar(select(func.count()).select_from(ProcessedMessage)) == 0
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 1

    asyncio.run(exercise())


async def scenario(store, payload, quote, kind):
    """Create only test prerequisites for later HTTP actions; no runtime shortcut."""
    payload = copy.deepcopy(payload)
    simulated = kind in {
        "PaymentSucceeded",
        "PaymentFailed",
        "PaymentRefunded",
        "PaymentRefundFailed",
    }
    payload["paymentMethod"] = "SIMULATED" if simulated else "COD"
    if kind in {"StockReserved", "StockReservationFailed"}:
        command = await create(store, payload, quote)
        values = (
            {"reservationId": str(uuid4()), "items": command.payload["items"]}
            if kind == "StockReserved"
            else {
                "code": "INSUFFICIENT_STOCK",
                "shortages": [
                    {
                        "productId": command.payload["items"][0]["productId"],
                        "requested": 2,
                        "available": 0,
                    }
                ],
            }
        )
        return response(command, kind, **values), command.aggregate_id
    initial, payment, _ = await reserve(store, payload, quote)
    if kind in {"PaymentInitialized", "PaymentSucceeded", "PaymentFailed"}:
        status = {
            "PaymentInitialized": "AWAITING_COLLECTION",
            "PaymentSucceeded": "SUCCEEDED",
            "PaymentFailed": "FAILED",
        }[kind]
        values = {
            "paymentId": str(uuid4()),
            "paymentVersion": 1,
            "paymentStatus": status,
            "amount": "430000",
            "currency": "VND",
        }
        if kind != "PaymentFailed":
            values["method"] = payload["paymentMethod"]
        else:
            values["code"] = "SIMULATED_DECLINE"
        return response(payment, kind, **values), initial.aggregate_id
    if kind == "PaymentCommandRejected":
        return response(
            payment,
            kind,
            rejectedType="InitializeCodPayment",
            code="OPERATION_CONFLICT",
            paymentId=None,
            paymentVersion=None,
            paymentStatus=None,
        ), initial.aggregate_id
    command_kind = {
        "StockReleased": "ReleaseStock",
        "StockReleaseFailed": "ReleaseStock",
        "StockCommitted": "CommitStock",
        "StockCommitFailed": "CommitStock",
        "CodCollected": "RecordCodCollection",
        "CodPaymentCancelled": "CancelCodPayment",
        "PaymentRefunded": "RefundPayment",
        "PaymentRefundFailed": "RefundPayment",
    }[kind]
    async with store["sessions"]() as session, session.begin():
        order = await session.get(OrderRecord, initial.aggregate_id)
        flow = await session.get(OrderWorkflow, initial.aggregate_id)
        order.payment_id, order.payment_version = uuid4(), 1
        order.payment_status = (
            PaymentStatus.SUCCEEDED if simulated else PaymentStatus.AWAITING_COLLECTION
        )
        order.status = OrderStatus.CANCELLING
        flow.phase, flow.state = WorkflowPhase.CANCELLATION, WorkflowState.WAITING
        flow.stock_step = StockStep.RELEASED
        flow.payment_step = PaymentStep.REFUND_PENDING if simulated else PaymentStep.CANCEL_PENDING
        operation = uuid4()
        values = {"orderId": str(order.id), "operationId": str(operation)}
        event_values = {}
        if command_kind in {"ReleaseStock", "CommitStock"}:
            flow.stock_step = (
                StockStep.RELEASE_PENDING
                if command_kind == "ReleaseStock"
                else StockStep.COMMIT_PENDING
            )
            values["reservationId"] = str(flow.reservation_id)
            event_values["reservationId"] = str(flow.reservation_id)
            if command_kind == "ReleaseStock":
                flow.release_operation_id = operation
                flow.payment_step, order.payment_status = (
                    PaymentStep.CANCELLED,
                    PaymentStatus.CANCELLED,
                )
                values["reason"] = "CUSTOMER_CANCELLED"
            else:
                flow.commit_operation_id = operation
                flow.phase, order.status = WorkflowPhase.DISPATCH, OrderStatus.PREPARING
                flow.payment_step = PaymentStep.COD_READY
            if kind.endswith("Failed"):
                event_values["code"] = "RESERVATION_STATE_CONFLICT"
        else:
            values["paymentId"] = str(order.payment_id)
            event_values = {
                "paymentId": str(order.payment_id),
                "paymentVersion": 2,
                "paymentStatus": "CANCELLED",
                "amount": "430000",
                "currency": "VND",
            }
            if command_kind == "RecordCodCollection":
                flow.collection_operation_id = operation
                flow.phase, order.status = WorkflowPhase.COMPLETION, OrderStatus.SHIPPING
                flow.stock_step, flow.payment_step = (
                    StockStep.COMMITTED,
                    PaymentStep.COLLECT_PENDING,
                )
                values["collectedBy"] = str(uuid4())
                event_values.update(paymentStatus="SUCCEEDED", collectedBy=values["collectedBy"])
            elif command_kind == "CancelCodPayment":
                flow.cancel_payment_operation_id = operation
                values["reason"] = "CUSTOMER_CANCELLED"
            else:
                flow.refund_operation_id = operation
                values.update(amount="430000", currency="VND", reason="CUSTOMER_CANCELLED")
                event_values.update(paymentStatus="REFUNDED", refundId=str(uuid4()))
                if kind == "PaymentRefundFailed":
                    event_values.pop("amount")
                    event_values.pop("currency")
                    event_values.update(
                        paymentStatus="REFUND_PENDING",
                        code="SIMULATED_REFUND_RETRY",
                        retryable=True,
                    )
        command = OutboxMessage(
            message_type=command_kind,
            aggregate_type="ORDER",
            aggregate_id=order.id,
            exchange_name="commerce.commands",
            routing_key=COMMANDS[command_kind][0],
            correlation_id=flow.correlation_id,
            payload=values,
        )
        session.add(command)
        await session.flush()
    return response(command, kind, **event_values), initial.aggregate_id


@pytest.mark.parametrize("kind", list(EVENTS))
def test_all_fourteen_events_dispatch_into_real_transactions(
    order_runtime_store, create_payload, quote_payload, kind
):
    async def exercise():
        event, order_id = await scenario(order_runtime_store, create_payload, quote_payload, kind)
        processor = InboxProcessor(order_runtime_store["sessions"])
        assert await processor.process(event) == "applied"
        assert await processor.process(event) == "duplicate"
        async with order_runtime_store["sessions"]() as session:
            row = await session.get(OrderRecord, order_id)
            if kind in {"PaymentInitialized", "PaymentSucceeded"}:
                assert row.status == OrderStatus.AWAITING_CONFIRMATION
            elif kind == "StockReservationFailed":
                assert row.status == OrderStatus.REJECTED
            elif kind == "StockCommitted":
                assert row.status == OrderStatus.SHIPPING
            elif kind == "CodCollected":
                assert row.status == OrderStatus.COMPLETED
            elif kind in {"StockReleased", "CodPaymentCancelled", "PaymentRefunded"}:
                assert row.status == OrderStatus.CANCELLED
            elif (
                kind.endswith("Failed")
                and kind != "PaymentFailed"
                or kind == "PaymentCommandRejected"
            ):
                assert row.requires_attention
            if kind == "PaymentFailed":
                assert row.status == OrderStatus.CANCELLING
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboxMessage)
                        .where(OutboxMessage.message_type == "ReleaseStock")
                    )
                    == 1
                )

    asyncio.run(exercise())


def test_refund_failure_then_success_same_operation_is_not_discarded(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        event, order_id = await scenario(
            order_runtime_store, create_payload, quote_payload, "PaymentRefundFailed"
        )
        processor = InboxProcessor(order_runtime_store["sessions"])
        assert await processor.process(event) == "applied"
        async with order_runtime_store["sessions"]() as session:
            command = await session.get(OutboxMessage, event.envelope.causation_id)
        success = response(
            command,
            "PaymentRefunded",
            paymentId=event.envelope.payload["paymentId"],
            paymentVersion=3,
            paymentStatus="REFUNDED",
            refundId=event.envelope.payload["refundId"],
            amount="430000",
            currency="VND",
        )
        assert await processor.process(success) == "applied"
        old = event.envelope.model_copy(update={"message_id": uuid4()})
        assert (
            await processor.process(
                decode_event(old.model_dump_json().encode(), EVENTS["PaymentRefundFailed"][0])
            )
            == "ignored"
        )
        async with order_runtime_store["sessions"]() as session:
            row = await session.get(OrderRecord, order_id)
            assert (
                row.status == OrderStatus.CANCELLED
                and row.payment_status == PaymentStatus.REFUNDED
                and row.payment_version == 3
            )

    asyncio.run(exercise())


@pytest.mark.parametrize("invalid", ["amount", "payment-id", "version-conflict", "version-gap"])
def test_payment_identity_and_version_guard_preserve_current_state(
    order_runtime_store, create_payload, quote_payload, invalid
):
    async def exercise():
        create_payload["paymentMethod"] = "SIMULATED"
        _, command, _ = await reserve(order_runtime_store, create_payload, quote_payload)
        payment_id = uuid4()
        async with order_runtime_store["sessions"]() as session, session.begin():
            order = await session.get(OrderRecord, command.aggregate_id)
            order.payment_id, order.payment_version, order.payment_status = (
                payment_id,
                1,
                PaymentStatus.PENDING,
            )
        event = response(
            command,
            "PaymentSucceeded",
            paymentId=str(uuid4() if invalid == "payment-id" else payment_id),
            paymentVersion=3
            if invalid == "version-gap"
            else (1 if invalid == "version-conflict" else 2),
            paymentStatus="SUCCEEDED",
            method="SIMULATED",
            amount="1" if invalid == "amount" else "430000",
            currency="VND",
        )
        expected = EventRetryable if invalid == "version-gap" else MessageInvalid
        with pytest.raises(expected):
            await InboxProcessor(order_runtime_store["sessions"]).process(event)
        async with order_runtime_store["sessions"]() as session:
            order = await session.get(OrderRecord, command.aggregate_id)
            assert (
                order.status == OrderStatus.PROCESSING
                and order.payment_status == PaymentStatus.PENDING
            )
            assert await session.scalar(select(func.count()).select_from(ProcessedMessage)) == 1

    asyncio.run(exercise())
