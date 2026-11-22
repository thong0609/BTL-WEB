import asyncio
import os
import subprocess
import sys
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from test_lifecycle_api import api, command, emit, post, ready, state
from test_worker_database import create, reserve, response

from commerce_order.clients.recovery import InventorySnapshot, PaymentSnapshot, RecoveryUnavailable
from commerce_order.domain.enums import OrderStatus, PaymentStatus
from commerce_order.messaging.inbox import InboxProcessor
from commerce_order.messaging.schemas import EventRetryable, MessageInvalid, PaymentEvidence
from commerce_order.models import OrderWorkflow, OutboxMessage, ProcessedMessage
from commerce_order.models.messaging import OutboxStatus
from commerce_order.services.recovery import RecoveryJob
from commerce_order.settings import Settings

pytestmark = pytest.mark.integration


class Source:
    def __init__(self, value=None, callback=None):
        self.value, self.callback = value, callback

    async def get(self, order_id, correlation_id):
        if self.callback:
            await self.callback()
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def inventory(order_id, reservation_id, status, *events):
    return InventorySnapshot.model_validate(
        {
            "orderId": str(order_id),
            "reservationId": str(reservation_id),
            "status": status,
            "version": 1,
            "events": [event.envelope.model_dump(mode="json") for event in events],
        }
    )


def payment(
    order_id,
    payment_id,
    status,
    version,
    method,
    *events,
    operation_id=None,
    source_id=None,
    amount="430000",
):
    return PaymentSnapshot.model_validate(
        {
            "orderId": str(order_id),
            "paymentId": str(payment_id),
            "status": status,
            "version": version,
            "method": method,
            "amount": amount,
            "currency": "VND",
            "operationId": str(operation_id) if operation_id else None,
            "commandMessageId": str(source_id) if source_id else None,
            "events": [event.envelope.model_dump(mode="json") for event in events],
        }
    )


def job(store, stock=None, money=None, **options):
    return RecoveryJob(
        store["sessions"],
        stock or Source(),
        money or Source(),
        Settings(
            app_env="test",
            order_recovery_stale_seconds=0,
            order_recovery_poll_seconds=0.05,
            **options,
        ),
    )


async def due(store):
    async with store["sessions"]() as session, session.begin():
        await session.execute(
            update(OrderWorkflow).values(
                next_retry_at=func.clock_timestamp() - timedelta(seconds=1)
            )
        )


async def published(store, source):
    async with store["sessions"]() as session, session.begin():
        row = await session.get(OutboxMessage, source.id)
        row.status, row.published_at = OutboxStatus.PUBLISHED, func.clock_timestamp()


def test_missing_stock_event_is_replayed_from_original_receipt(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        store = order_runtime_store
        source = await create(store, create_payload, quote_payload)
        await published(store, source)
        reservation_id = uuid4()
        event = response(
            source,
            "StockReserved",
            reservationId=str(reservation_id),
            items=source.payload["items"],
        )
        recovery = job(
            store, Source(inventory(source.aggregate_id, reservation_id, "RESERVED", event))
        )
        assert await recovery.once() == 1
        order, flow = await state(store, source.aggregate_id)
        assert (
            order.status == OrderStatus.PROCESSING
            and flow.stock_step == "RESERVED"
            and flow.payment_operation_id
        )
        await due(store)
        await recovery.once()
        async with store["sessions"]() as session:
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 2
            assert await session.scalar(select(func.count()).select_from(ProcessedMessage)) == 1

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "kind,method", [("PaymentInitialized", "COD"), ("PaymentSucceeded", "SIMULATED")]
)
def test_missing_payment_event_advances_checkout_using_original_receipt(
    order_runtime_store, create_payload, quote_payload, kind, method
):
    async def exercise():
        store = order_runtime_store
        create_payload["paymentMethod"] = method
        initial, source, stock = await reserve(store, create_payload, quote_payload)
        pid = uuid4()
        status = "AWAITING_COLLECTION" if method == "COD" else "SUCCEEDED"
        event = response(
            source,
            kind,
            paymentId=str(pid),
            paymentVersion=1,
            paymentStatus=status,
            method=method,
            amount="430000",
            currency="VND",
        )
        recovery = job(
            store,
            Source(
                inventory(initial.aggregate_id, stock.payload.reservation_id, "RESERVED", stock)
            ),
            Source(payment(initial.aggregate_id, pid, status, 1, method, event)),
        )
        await recovery.once()
        order, flow = await state(store, initial.aggregate_id)
        assert order.status == OrderStatus.AWAITING_CONFIRMATION and flow.phase == "IDLE"
        assert order.payment_id == pid and order.payment_version == 1
        assert await recovery.once() == 0

    asyncio.run(exercise())


def test_pending_payment_stays_processing_without_reissuing_charge(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        store = order_runtime_store
        create_payload["paymentMethod"] = "SIMULATED"
        initial, source, _ = await reserve(store, create_payload, quote_payload)
        await published(store, source)
        pid = uuid4()
        snapshot = payment(
            initial.aggregate_id,
            pid,
            "PENDING",
            1,
            "SIMULATED",
            operation_id=source.payload["operationId"],
            source_id=source.id,
        )
        recovery = job(store, money=Source(snapshot))
        await recovery.once()
        order, flow = await state(store, initial.aggregate_id)
        assert (
            order.status == OrderStatus.PROCESSING and order.payment_status == PaymentStatus.PENDING
        )
        assert flow.stock_step == "RESERVED" and flow.payment_step == "PENDING"
        async with store["sessions"]() as session:
            row = await session.get(OutboxMessage, source.id)
            assert row.status == OutboxStatus.PUBLISHED
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 2
        await emit(store, initial.aggregate_id, "ProcessPayment", "PaymentSucceeded")
        assert (await state(store, initial.aggregate_id))[
            0
        ].status == OrderStatus.AWAITING_CONFIRMATION

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["404", "timeout"])
def test_unknown_result_only_retries_same_command_and_flags_attention(
    order_runtime_store, create_payload, quote_payload, failure
):
    async def exercise():
        store = order_runtime_store
        source = await create(store, create_payload, quote_payload)
        await published(store, source)
        unavailable = (
            RecoveryUnavailable("private dependency failure") if failure == "timeout" else None
        )
        recovery = job(
            store, Source(unavailable), Source(unavailable), order_recovery_max_attempts=1
        )
        await recovery.once()
        order, flow = await state(store, source.aggregate_id)
        assert order.status == OrderStatus.PROCESSING and order.requires_attention
        assert flow.stock_step == "RESERVE_PENDING" and flow.state == "NEEDS_ATTENTION"
        async with store["sessions"]() as session:
            row = await session.get(OutboxMessage, source.id)
            assert row.status == OutboxStatus.PENDING and row.payload == source.payload
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 1
        await due(store)
        await recovery.once()
        assert (await state(store, source.aggregate_id))[0].status == OrderStatus.PROCESSING

    asyncio.run(exercise())


@pytest.mark.parametrize("bad", ["order", "amount", "reservation"])
def test_mismatched_snapshot_cannot_update_payment_or_stock(
    order_runtime_store, create_payload, quote_payload, bad
):
    async def exercise():
        store = order_runtime_store
        create_payload["paymentMethod"] = "SIMULATED"
        initial, source, stock = await reserve(store, create_payload, quote_payload)
        event = response(
            source,
            "PaymentSucceeded",
            paymentId=str(uuid4()),
            paymentVersion=1,
            paymentStatus="SUCCEEDED",
            method="SIMULATED",
            amount="430000",
            currency="VND",
        )
        snapshot = payment(
            uuid4() if bad == "order" else initial.aggregate_id,
            event.envelope.payload["paymentId"],
            "SUCCEEDED",
            1,
            "SIMULATED",
            event,
            amount="1" if bad == "amount" else "430000",
        )
        inventory_source = Source(
            inventory(
                initial.aggregate_id,
                uuid4() if bad == "reservation" else stock.payload.reservation_id,
                "RESERVED",
                stock,
            )
        )
        await job(store, inventory_source, Source(snapshot)).once()
        order, _ = await state(store, initial.aggregate_id)
        assert (
            order.status == OrderStatus.PROCESSING
            and order.payment_status is None
            and order.requires_attention
        )
        async with store["sessions"]() as session:
            assert await session.scalar(select(func.count()).select_from(ProcessedMessage)) == 1

    asyncio.run(exercise())


def test_two_jobs_share_work_and_stale_claim_cannot_apply_snapshot(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        store = order_runtime_store
        source = await create(store, create_payload, quote_payload)
        rid = uuid4()
        event = response(
            source, "StockReserved", reservationId=str(rid), items=source.payload["items"]
        )
        first, second = (
            job(store, Source(inventory(source.aggregate_id, rid, "RESERVED", event))),
            job(store, Source(inventory(source.aggregate_id, rid, "RESERVED", event))),
        )
        batches = await asyncio.gather(first.claim(), second.claim())
        assert sorted(len(batch) for batch in batches) == [0, 1]
        old = (batches[0] or batches[1])[0]
        await due(store)
        replacement = (await second.claim())[0]
        await first.reconcile(old)
        assert (await state(store, source.aggregate_id))[1].stock_step == "RESERVE_PENDING"
        await second.reconcile(replacement)
        assert (await state(store, source.aggregate_id))[1].stock_step == "RESERVED"

    asyncio.run(exercise())


def test_event_arriving_during_http_lookup_supersedes_snapshot(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        store = order_runtime_store
        source = await create(store, create_payload, quote_payload)
        rid = uuid4()
        event = response(
            source, "StockReserved", reservationId=str(rid), items=source.payload["items"]
        )

        async def network_race():
            # This succeeds only because recovery holds no DB lock while doing HTTP.
            await InboxProcessor(store["sessions"]).process(event)

        await job(
            store, Source(inventory(source.aggregate_id, rid, "RESERVED", event), network_race)
        ).once()
        async with store["sessions"]() as session:
            assert await session.scalar(select(func.count()).select_from(ProcessedMessage)) == 1
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 2
        assert not (await state(store, source.aggregate_id))[0].requires_attention

    asyncio.run(exercise())


def test_refund_retry_keeps_operation_and_only_retries_money_branch(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        store = order_runtime_store
        create_payload["paymentMethod"] = "SIMULATED"
        order_id = await ready(store, create_payload, quote_payload)
        async with api(store) as client:
            await post(
                client,
                order_id,
                "cancel",
                {"reason": "return funds"},
                actor="customer-a",
                customer=True,
            )
        release = await emit(store, order_id, "ReleaseStock", "StockReleased")
        failed = await emit(store, order_id, "RefundPayment", "PaymentRefundFailed")
        source = await command(store, order_id, "RefundPayment")
        await published(store, source)
        order, flow = await state(store, order_id)
        money = Source(
            payment(order_id, order.payment_id, "REFUND_PENDING", 2, "SIMULATED", failed)
        )
        recovery = job(
            store, Source(inventory(order_id, flow.reservation_id, "RELEASED", release)), money
        )
        await recovery.once()
        async with store["sessions"]() as session:
            refunds = list(
                await session.scalars(
                    select(OutboxMessage).where(OutboxMessage.message_type == "RefundPayment")
                )
            )
            assert len(refunds) == 2 and refunds[0].payload == refunds[1].payload
            assert refunds[0].id != refunds[1].id
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(OutboxMessage.message_type == "ReleaseStock")
                )
                == 1
            )
        await due(store)
        await recovery.once()
        async with store["sessions"]() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(OutboxMessage.message_type == "RefundPayment")
                )
                == 2
            )
        retry = await command(store, order_id, "RefundPayment")
        success = response(
            retry,
            "PaymentRefunded",
            paymentId=str(order.payment_id),
            paymentVersion=3,
            paymentStatus="REFUNDED",
            refundId=failed.envelope.payload["refundId"],
            amount="430000",
            currency="VND",
        )
        money.value = payment(
            order_id, order.payment_id, "REFUNDED", 3, "SIMULATED", failed, success
        )
        await due(store)
        await recovery.once()
        assert (await state(store, order_id))[0].status == OrderStatus.CANCELLED
        assert await recovery.once() == 0

    asyncio.run(exercise())


def test_recovery_cli_once_does_not_require_or_connect_broker(order_runtime_store):
    env = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_ENABLED": "true",
        "DATABASE_URL": order_runtime_store["url"],
        "DB_SSL_MODE": "disable",
        "BROKER_ENABLED": "false",
        "BROKER_URL": "amqp://unused:private-secret@127.0.0.1:1/",
    }
    result = subprocess.run(
        [sys.executable, "-m", "commerce_order.worker", "--run", "--mode", "recovery", "--once"],
        env=env,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0 and '"count": 0' in result.stdout
    assert "private-secret" not in result.stdout + result.stderr


def test_confirmed_refund_snapshot_recovers_version_gap_without_trusting_broker_gap(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        store = order_runtime_store
        create_payload["paymentMethod"] = "SIMULATED"
        order_id = await ready(store, create_payload, quote_payload)
        async with api(store) as client:
            await post(
                client,
                order_id,
                "cancel",
                {"reason": "refund fixture"},
                actor="customer-a",
                customer=True,
            )
        released = await emit(store, order_id, "ReleaseStock", "StockReleased")
        source = await command(store, order_id, "RefundPayment")
        order, flow = await state(store, order_id)
        result = response(
            source,
            "PaymentRefunded",
            paymentId=str(order.payment_id),
            paymentVersion=3,
            paymentStatus="REFUNDED",
            refundId=str(uuid4()),
            amount="430000",
            currency="VND",
        )
        # Missing an intermediate producer version must still be rejected on the broker path.
        with pytest.raises(EventRetryable):
            await InboxProcessor(store["sessions"]).process(result)
        snapshot = payment(order_id, order.payment_id, "REFUNDED", 3, "SIMULATED", result)
        evidence = PaymentEvidence(
            result.envelope.message_id,
            order_id,
            order.payment_id,
            3,
            PaymentStatus.REFUNDED,
            order.payment_method,
            430000,
            "VND",
        )
        with pytest.raises(MessageInvalid, match="RECOVERY_FENCE_REQUIRED"):
            await InboxProcessor(store["sessions"]).process(result, payment_evidence=evidence)
        recovery = job(
            store,
            Source(inventory(order_id, flow.reservation_id, "RELEASED", released)),
            Source(snapshot),
        )
        await recovery.once()
        restored, _ = await state(store, order_id)
        assert restored.status == OrderStatus.CANCELLED
        assert restored.payment_version == 3 and restored.payment_status == PaymentStatus.REFUNDED
        async with store["sessions"]() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(OutboxMessage.message_type == "RefundPayment")
                )
                == 1
            )

    asyncio.run(exercise())
