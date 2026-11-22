import asyncio
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from test_worker_database import ACTOR, create, reserve, response

from commerce_backend_common.errors import ServiceError
from commerce_gateway.main import create_app as gateway_app
from commerce_gateway.settings import Settings as GatewaySettings
from commerce_order.domain.enums import ActorRole, OrderStatus, PaymentStatus
from commerce_order.domain.transitions import Actor
from commerce_order.main import create_app
from commerce_order.messaging.inbox import InboxProcessor
from commerce_order.messaging.schemas import MessageInvalid
from commerce_order.models import (
    OrderActionRequest,
    OrderRecord,
    OrderStatusHistory,
    OrderWorkflow,
    OutboxMessage,
)
from commerce_order.settings import Settings

pytestmark = pytest.mark.integration
ADMIN = Actor(UUID("10000000-0000-4000-8000-000000000003"), ActorRole.ADMIN)
B = Actor(UUID("10000000-0000-4000-8000-000000000002"), ActorRole.CUSTOMER)


@asynccontextmanager
async def api(store):
    async def verify(token):
        actor = {"customer-a": ACTOR, "customer-b": B, "admin": ADMIN}.get(token)
        if actor is None:
            raise ServiceError(401, "AUTH_INVALID", "Invalid test principal")
        return actor

    order = create_app(
        Settings(
            app_env="test", database_enabled=True, database_url=store["url"], db_ssl_mode="disable"
        ),
        token_verifier=verify,
    )
    gateway = gateway_app(
        GatewaySettings(app_env="test"), order_transport=httpx.ASGITransport(order)
    )
    async with (
        order.router.lifespan_context(order),
        gateway.router.lifespan_context(gateway),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(gateway), base_url="http://gateway.test"
        ) as client,
    ):
        yield client


async def post(client, order_id, action, body=None, *, actor="admin", key=None, customer=False):
    prefix = "/api/v1/orders" if customer else "/api/v1/admin/orders"
    kwargs = {"json": body} if body is not None else {}
    return await client.post(
        f"{prefix}/{order_id}/{action}",
        headers={"Authorization": f"Bearer {actor}", "Idempotency-Key": key or uuid4().hex},
        **kwargs,
    )


async def command(store, order_id, kind):
    async with store["sessions"]() as session:
        return await session.scalar(
            select(OutboxMessage)
            .where(OutboxMessage.aggregate_id == order_id, OutboxMessage.message_type == kind)
            .order_by(OutboxMessage.created_at.desc(), OutboxMessage.id.desc())
        )


async def emit(store, order_id, command_kind, event_kind, **extra):
    source = await command(store, order_id, command_kind)
    assert source is not None
    async with store["sessions"]() as session:
        order = await session.get(OrderRecord, order_id)
        flow = await session.get(OrderWorkflow, order_id)
        if event_kind.startswith("Stock"):
            payload = {"reservationId": str(flow.reservation_id)}
        else:
            status = {
                "PaymentInitialized": "AWAITING_COLLECTION",
                "PaymentSucceeded": "SUCCEEDED",
                "PaymentFailed": "FAILED",
                "CodCollected": "SUCCEEDED",
                "CodPaymentCancelled": "CANCELLED",
                "PaymentRefunded": "REFUNDED",
                "PaymentRefundFailed": "REFUND_PENDING",
            }[event_kind]
            payload = {
                "paymentId": str(order.payment_id or uuid4()),
                "paymentVersion": (order.payment_version or 0) + 1,
                "paymentStatus": status,
                "amount": str(order.total_amount),
                "currency": "VND",
            }
            if event_kind in {"PaymentInitialized", "PaymentSucceeded"}:
                payload["method"] = order.payment_method.value
            if event_kind == "CodCollected":
                payload["collectedBy"] = source.payload["collectedBy"]
            if event_kind in {"PaymentRefunded", "PaymentRefundFailed"}:
                payload["refundId"] = str(uuid4())
            if event_kind == "PaymentRefundFailed":
                payload.pop("amount")
                payload.pop("currency")
                payload.update(code="TEMPORARY_REFUND_FAILURE", retryable=True)
        event = response(source, event_kind, **{**payload, **extra})
    await InboxProcessor(store["sessions"]).process(event)
    return event


async def ready(store, payload, quote):
    initial, payment, _ = await reserve(store, payload, quote)
    kind = "PaymentInitialized" if payload["paymentMethod"] == "COD" else "PaymentSucceeded"
    await emit(store, initial.aggregate_id, payment.message_type, kind)
    return initial.aggregate_id


async def state(store, order_id):
    async with store["sessions"]() as session:
        return await session.get(OrderRecord, order_id), await session.get(OrderWorkflow, order_id)


async def shipping(client, store, order_id):
    assert (await post(client, order_id, "confirm")).status_code == 200
    assert (await post(client, order_id, "dispatch")).status_code == 202
    await emit(store, order_id, "CommitStock", "StockCommitted")


def test_cod_full_lifecycle_waits_for_inventory_and_collection(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        store = order_runtime_store
        order_id = await ready(store, create_payload, quote_payload)
        async with api(store) as client:
            confirmed = await post(client, order_id, "confirm", key="confirm-once")
            assert confirmed.status_code == 200 and confirmed.json()["status"] == "PREPARING"
            dispatched = await post(client, order_id, "dispatch", key="dispatch-once")
            assert dispatched.status_code == 202 and dispatched.json()["status"] == "PREPARING"
            assert (
                await post(
                    client,
                    order_id,
                    "cancel",
                    {"reason": "too late"},
                    actor="customer-a",
                    customer=True,
                )
            ).status_code == 409
            await emit(store, order_id, "CommitStock", "StockCommitted")
            bad = await post(
                client,
                order_id,
                "complete",
                {"delivered": True, "codCollected": False},
                key="complete-once",
            )
            assert bad.status_code == 400
            completed = await post(
                client,
                order_id,
                "complete",
                {"delivered": True, "codCollected": True},
                key="complete-once",
            )
            assert completed.status_code == 202 and completed.json()["status"] == "SHIPPING"
            collection = await command(store, order_id, "RecordCodCollection")
            assert collection.payload["collectedBy"] == str(ADMIN.user_id)
            await emit(store, order_id, "RecordCodCollection", "CodCollected")
            replay = await post(
                client,
                order_id,
                "complete",
                {"delivered": True, "codCollected": True},
                key="complete-once",
            )
            assert replay.json() == completed.json()
            detail = await client.get(
                f"/api/v1/orders/{order_id}", headers={"Authorization": "Bearer customer-a"}
            )
            assert detail.status_code == 200 and detail.json()["status"] == "COMPLETED"
            assert (
                detail.json()["paymentStatus"] == "SUCCEEDED"
                and detail.json()["totalAmount"] == "430000"
            )
        async with store["sessions"]() as session:
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 4
            assert await session.scalar(select(func.count()).select_from(OrderStatusHistory)) == 5
            action = await session.scalar(
                select(OrderActionRequest).where(
                    OrderActionRequest.idempotency_key == "complete-once"
                )
            )
            assert action.request_body == {"delivered": True, "codCollected": True}

    asyncio.run(exercise())


def test_simulated_full_lifecycle_has_no_cod_collection(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        store = order_runtime_store
        create_payload["paymentMethod"] = "SIMULATED"
        order_id = await ready(store, create_payload, quote_payload)
        async with api(store) as client:
            await shipping(client, store, order_id)
            result = await post(
                client, order_id, "complete", {"delivered": True}, key="sim-complete"
            )
            assert result.status_code == 202 and result.json()["status"] == "COMPLETED"
            assert (
                await post(client, order_id, "complete", {"delivered": True}, key="sim-complete")
            ).json() == result.json()
        async with store["sessions"]() as session:
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 3
            assert await command(store, order_id, "RecordCodCollection") is None

    asyncio.run(exercise())


@pytest.mark.parametrize("method", ["COD", "SIMULATED"])
@pytest.mark.parametrize("money_first", [False, True])
def test_cancel_waits_for_both_branches_and_replays_after_completion(
    order_runtime_store, create_payload, quote_payload, method, money_first
):
    async def exercise():
        store = order_runtime_store
        create_payload["paymentMethod"] = method
        order_id = await ready(store, create_payload, quote_payload)
        money_command, money_event = (
            ("CancelCodPayment", "CodPaymentCancelled")
            if method == "COD"
            else ("RefundPayment", "PaymentRefunded")
        )
        async with api(store) as client:
            original = await post(
                client,
                order_id,
                "cancel",
                {"reason": "changed mind"},
                actor="customer-a",
                key="cancel-once",
                customer=True,
            )
            assert original.status_code == 202 and original.json()["status"] == "CANCELLING"
            branches = [("ReleaseStock", "StockReleased"), (money_command, money_event)]
            if money_first:
                branches.reverse()
            await emit(store, order_id, *branches[0])
            assert (await state(store, order_id))[0].status == OrderStatus.CANCELLING
            await emit(store, order_id, *branches[1])
            assert (await state(store, order_id))[0].status == OrderStatus.CANCELLED
            assert (
                await post(
                    client,
                    order_id,
                    "cancel",
                    {"reason": "changed mind"},
                    actor="customer-a",
                    key="cancel-once",
                    customer=True,
                )
            ).json() == original.json()
            assert (
                await post(
                    client,
                    order_id,
                    "cancel",
                    {"reason": "new reason"},
                    actor="customer-a",
                    key="cancel-once",
                    customer=True,
                )
            ).status_code == 409
            already = await post(
                client,
                order_id,
                "cancel",
                {"reason": "already done"},
                actor="customer-a",
                key="cancel-again",
                customer=True,
            )
            assert already.status_code == 202 and already.json()["status"] == "CANCELLED"
        async with store["sessions"]() as session:
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 4
            if method == "SIMULATED":
                refund = await command(store, order_id, "RefundPayment")
                assert refund.payload["amount"] == "430000"

    asyncio.run(exercise())


def test_refund_error_keeps_cancelling_then_new_result_finishes(
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
            await emit(store, order_id, "ReleaseStock", "StockReleased")
            failed = await emit(store, order_id, "RefundPayment", "PaymentRefundFailed")
            order, flow = await state(store, order_id)
            assert (
                order.status == OrderStatus.CANCELLING
                and order.requires_attention
                and flow.stock_step == "RELEASED"
            )
            await emit(
                store,
                order_id,
                "RefundPayment",
                "PaymentRefunded",
                refundId=failed.envelope.payload["refundId"],
            )
            order, _ = await state(store, order_id)
            assert (
                order.status == OrderStatus.CANCELLED
                and order.payment_status == PaymentStatus.REFUNDED
            )
        async with store["sessions"]() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(OutboxMessage.message_type == "ReleaseStock")
                )
                == 1
            )

    asyncio.run(exercise())


@pytest.mark.parametrize("outcome", ["success", "failure", "stock-shortage"])
def test_checkout_results_and_delays_never_invent_payment_outcome(
    order_runtime_store, create_payload, quote_payload, outcome
):
    async def exercise():
        store = order_runtime_store
        create_payload["paymentMethod"] = "SIMULATED"
        if outcome == "stock-shortage":
            source = await create(store, create_payload, quote_payload)
            event = response(
                source,
                "StockReservationFailed",
                code="INSUFFICIENT_STOCK",
                shortages=[
                    {
                        "productId": source.payload["items"][0]["productId"],
                        "requested": 2,
                        "available": 0,
                    }
                ],
            )
            await InboxProcessor(store["sessions"]).process(event)
            assert (await state(store, source.aggregate_id))[0].status == OrderStatus.REJECTED
            assert await command(store, source.aggregate_id, "ProcessPayment") is None
            return
        initial, _, _ = await reserve(store, create_payload, quote_payload)
        order_id = initial.aggregate_id
        order, flow = await state(store, order_id)
        assert (
            order.status == OrderStatus.PROCESSING
            and order.payment_status is None
            and flow.stock_step == "RESERVED"
        )
        if outcome == "success":
            await emit(store, order_id, "ProcessPayment", "PaymentSucceeded")
            assert (await state(store, order_id))[0].status == OrderStatus.AWAITING_CONFIRMATION
        else:
            failure = await emit(
                store, order_id, "ProcessPayment", "PaymentFailed", code="SIMULATED_DECLINE"
            )
            assert (await state(store, order_id))[0].status == OrderStatus.CANCELLING
            await emit(store, order_id, "ReleaseStock", "StockReleased")
            order, _ = await state(store, order_id)
            assert order.status == OrderStatus.CANCELLED and order.cancel_reason == "PAYMENT_FAILED"
            assert await command(store, order_id, "RefundPayment") is None
            late = response(
                await command(store, order_id, "ProcessPayment"),
                "PaymentSucceeded",
                paymentId=failure.envelope.payload["paymentId"],
                paymentVersion=1,
                paymentStatus="SUCCEEDED",
                method="SIMULATED",
                amount="430000",
                currency="VND",
            )
            with pytest.raises(MessageInvalid):
                await InboxProcessor(store["sessions"]).process(late)
            assert (await state(store, order_id))[0].status == OrderStatus.CANCELLED

    asyncio.run(exercise())


@pytest.mark.parametrize("race", ["confirm-cancel", "dispatch-cancel", "same-dispatch-key"])
def test_concurrent_actions_have_one_winner_or_one_replayed_result(
    order_runtime_store, create_payload, quote_payload, race
):
    async def exercise():
        store = order_runtime_store
        order_id = await ready(store, create_payload, quote_payload)
        async with api(store) as client:
            if race != "confirm-cancel":
                await post(client, order_id, "confirm")
            if race == "confirm-cancel":
                calls = [
                    post(client, order_id, "confirm"),
                    post(
                        client,
                        order_id,
                        "cancel",
                        {"reason": "cancel race"},
                        actor="customer-a",
                        customer=True,
                    ),
                ]
            elif race == "dispatch-cancel":
                calls = [
                    post(client, order_id, "dispatch"),
                    post(client, order_id, "cancel", {"reason": "cancel race"}),
                ]
            else:
                calls = [post(client, order_id, "dispatch", key="same-dispatch") for _ in range(2)]
            results = await asyncio.gather(*calls)
            if race == "same-dispatch-key":
                assert [r.status_code for r in results] == [202, 202] and results[
                    0
                ].json() == results[1].json()
            else:
                assert sum(result.status_code in {200, 202} for result in results) == 1
                assert sum(result.status_code == 409 for result in results) == 1
        assert not (
            await command(store, order_id, "CommitStock")
            and await command(store, order_id, "ReleaseStock")
        )
        async with store["sessions"]() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(OutboxMessage.message_type == "CommitStock")
                )
                <= 1
            )

    asyncio.run(exercise())


def test_scope_spoof_and_exception_audit_without_fake_history(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        store = order_runtime_store
        order_id = await ready(store, create_payload, quote_payload)
        async with api(store) as client:
            assert (
                await post(
                    client,
                    order_id,
                    "cancel",
                    {"reason": "not mine"},
                    actor="customer-b",
                    customer=True,
                )
            ).status_code == 404
            assert (await post(client, order_id, "confirm", actor="customer-a")).status_code == 403
            assert (
                await post(
                    client,
                    order_id,
                    "cancel",
                    {"reason": "wrong route"},
                    actor="admin",
                    customer=True,
                )
            ).status_code == 403
            await shipping(client, store, order_id)
            async with store["sessions"]() as session:
                before = await session.scalar(select(func.count()).select_from(OrderStatusHistory))
            for number in range(2):
                result = await post(
                    client,
                    order_id,
                    "exceptions",
                    {"reason": f"Delivery issue {number}"},
                    key=f"exception-{number}",
                )
                assert result.status_code == 200 and result.json()["status"] == "SHIPPING"
            async with store["sessions"]() as session:
                assert (
                    await session.scalar(select(func.count()).select_from(OrderStatusHistory))
                    == before
                )
                audits = list(
                    await session.scalars(
                        select(OrderActionRequest).where(
                            OrderActionRequest.action == "RECORD_EXCEPTION"
                        )
                    )
                )
                assert {r.request_body["reason"] for r in audits} == {
                    "Delivery issue 0",
                    "Delivery issue 1",
                }
                assert all(r.actor_id == ADMIN.user_id for r in audits)
                order = await session.get(OrderRecord, order_id)
                assert order.requires_attention and order.exception_note == "Delivery issue 1"

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "invalid",
    [
        "missing-key",
        "long-key",
        "empty-reason",
        "spoofed-total",
        "not-delivered",
        "extra-confirm-body",
    ],
)
def test_invalid_action_does_not_capture_key_or_create_commands(
    order_runtime_store, create_payload, quote_payload, invalid
):
    async def exercise():
        store = order_runtime_store
        order_id = await ready(store, create_payload, quote_payload)
        headers = {"Authorization": "Bearer admin", "Idempotency-Key": "invalid-action"}
        action, body = "cancel", {"reason": "a reason"}
        if invalid == "missing-key":
            headers.pop("Idempotency-Key")
        elif invalid == "long-key":
            headers["Idempotency-Key"] = "x" * 129
        elif invalid == "empty-reason":
            body["reason"] = "   "
        elif invalid == "spoofed-total":
            body["totalAmount"] = "1"
        elif invalid == "not-delivered":
            action, body = "complete", {"delivered": False}
        else:
            action, body = "confirm", {"status": "COMPLETED"}
        async with api(store) as client:
            result = await client.post(
                f"/api/v1/admin/orders/{order_id}/{action}", json=body, headers=headers
            )
            assert result.status_code == 400
        async with store["sessions"]() as session:
            assert await session.scalar(select(func.count()).select_from(OrderActionRequest)) == 0
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 2

    asyncio.run(exercise())


def test_cancel_database_fault_does_not_capture_key_or_leave_half_action(
    order_runtime_store, create_payload, quote_payload, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    from commerce_order.services.actions import OrderActions

    async def exercise():
        store = order_runtime_store
        create_payload["paymentMethod"] = "SIMULATED"
        order_id = await ready(store, create_payload, quote_payload)
        original = OrderActions.command

        def failing(session, locked, kind, values):
            original(session, locked, kind, values)
            if kind == "RefundPayment":
                raise OperationalError(
                    "injected write fault", {}, Exception("private-storage-detail")
                )

        async with api(store) as client:
            monkeypatch.setattr(OrderActions, "command", staticmethod(failing))
            result = await post(
                client,
                order_id,
                "cancel",
                {"reason": "cancel fixture"},
                actor="customer-a",
                customer=True,
                key="fault-retry-key",
            )
            assert result.status_code == 503 and "private-storage-detail" not in result.text
            async with store["sessions"]() as session:
                assert (
                    await session.scalar(select(func.count()).select_from(OrderActionRequest)) == 0
                )
                assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 2
            assert (await state(store, order_id))[0].status == OrderStatus.AWAITING_CONFIRMATION
            monkeypatch.setattr(OrderActions, "command", staticmethod(original))
            assert (
                await post(
                    client,
                    order_id,
                    "cancel",
                    {"reason": "cancel fixture"},
                    actor="customer-a",
                    customer=True,
                    key="fault-retry-key",
                )
            ).status_code == 202

    asyncio.run(exercise())
