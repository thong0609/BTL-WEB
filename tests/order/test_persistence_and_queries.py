import asyncio
import copy
from uuid import UUID

import httpx
import pytest
from fastapi import Request
from sqlalchemy import func, select

from commerce_backend_common.errors import ServiceError
from commerce_gateway.main import create_app as create_gateway
from commerce_gateway.settings import Settings as GatewaySettings
from commerce_order.api.dependencies import current_actor
from commerce_order.api.schemas import CreateOrder, Quote, Reason
from commerce_order.domain.enums import (
    ActorRole,
    OrderAction,
    OrderStatus,
    PaymentStatus,
    StockStep,
    WorkflowPhase,
    WorkflowState,
)
from commerce_order.domain.transitions import Actor, OrderRuleViolation
from commerce_order.main import create_app
from commerce_order.models import (
    HistoryActorType,
    IdempotencyRequest,
    OrderActionRequest,
    OrderItem,
    OrderRecord,
    OrderStatusHistory,
    OrderWorkflow,
    OutboxMessage,
)
from commerce_order.services.persistence import OrderPersistence, StoredResponse
from commerce_order.settings import Settings

pytestmark = pytest.mark.integration
A = Actor(UUID("10000000-0000-4000-8000-000000000001"), ActorRole.CUSTOMER)
B = Actor(UUID("10000000-0000-4000-8000-000000000002"), ActorRole.CUSTOMER)
ADMIN = Actor(UUID("10000000-0000-4000-8000-000000000003"), ActorRole.ADMIN)


async def accept(store, payload, quote_payload, actor=A, key="create-key"):
    async def loader():
        return Quote.model_validate(quote_payload)

    return await OrderPersistence(store["sessions"]).accept_order(
        actor, key, CreateOrder.model_validate(payload), loader
    )


def test_creation_is_atomic_and_replay_does_not_call_catalog(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        service = OrderPersistence(order_runtime_store["sessions"])
        original = await accept(order_runtime_store, create_payload, quote_payload)

        async def unavailable():
            raise RuntimeError("Catalog unavailable")

        replay = await service.accept_order(
            A, "create-key", CreateOrder.model_validate(create_payload), unavailable
        )
        assert replay.replayed and replay.body == original.body
        changed = copy.deepcopy(create_payload)
        changed["note"] = "different purchase"
        with pytest.raises(OrderRuleViolation, match="IDEMPOTENCY_CONFLICT"):
            await service.accept_order(
                A, "create-key", CreateOrder.model_validate(changed), unavailable
            )
        async with order_runtime_store["sessions"]() as session:
            for model in (
                OrderRecord,
                OrderItem,
                OrderWorkflow,
                OrderStatusHistory,
                IdempotencyRequest,
                OutboxMessage,
            ):
                assert await session.scalar(select(func.count()).select_from(model)) == 1
            message = await session.scalar(select(OutboxMessage))
            workflow = await session.get(OrderWorkflow, UUID(original.body["orderId"]))
            assert message.payload["operationId"] == str(workflow.reserve_operation_id)
            assert message.payload["items"][0]["quantity"] == 2

    asyncio.run(exercise())


@pytest.mark.parametrize("different_payload", [False, True])
def test_concurrent_creations_rollback_the_unique_key_loser_completely(
    order_runtime_store, create_payload, quote_payload, different_payload
):
    async def exercise():
        barrier = asyncio.Barrier(2)

        class RacingPersistence(OrderPersistence):
            async def _write_order(self, *args, **kwargs):
                await barrier.wait()  # Both calls already missed the second lookup.
                return await super()._write_order(*args, **kwargs)

        service = RacingPersistence(order_runtime_store["sessions"])

        async def loader():
            return Quote.model_validate(quote_payload)

        async def submit(payload):
            return await service.accept_order(
                A, "racing-key", CreateOrder.model_validate(payload), loader
            )

        other = copy.deepcopy(create_payload)
        if different_payload:
            other["note"] = "different payload"
        results = await asyncio.wait_for(
            asyncio.gather(submit(create_payload), submit(other), return_exceptions=True),
            timeout=15,
        )
        if different_payload:
            assert sum(isinstance(result, StoredResponse) for result in results) == 1
            conflict = next(result for result in results if isinstance(result, OrderRuleViolation))
            assert conflict.code == "IDEMPOTENCY_CONFLICT"
        else:
            assert results[0].body == results[1].body
            assert sum(result.replayed for result in results) == 1
        async with order_runtime_store["sessions"]() as session:
            for model in (
                OrderRecord,
                OrderItem,
                OrderWorkflow,
                OrderStatusHistory,
                IdempotencyRequest,
                OutboxMessage,
            ):
                assert await session.scalar(select(func.count()).select_from(model)) == 1

    asyncio.run(exercise())


def test_price_rejection_and_write_failure_do_not_claim_keys(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        service = OrderPersistence(order_runtime_store["sessions"])
        wrong = copy.deepcopy(quote_payload)
        wrong["items"][0]["catalogVersion"] += 1

        async def changed():
            return Quote.model_validate(wrong)

        with pytest.raises(OrderRuleViolation, match="PRICE_CHANGED"):
            await service.accept_order(
                A, "same-key", CreateOrder.model_validate(create_payload), changed
            )

        class BrokenPersistence(OrderPersistence):
            async def _write_order(self, *args, **kwargs):
                await super()._write_order(*args, **kwargs)
                raise RuntimeError("crash before commit")

        async def valid():
            return Quote.model_validate(quote_payload)

        with pytest.raises(RuntimeError):
            await BrokenPersistence(order_runtime_store["sessions"]).accept_order(
                A, "same-key", CreateOrder.model_validate(create_payload), valid
            )
        async with order_runtime_store["sessions"]() as session:
            for model in (
                OrderRecord,
                IdempotencyRequest,
                OrderWorkflow,
                OutboxMessage,
                OrderStatusHistory,
            ):
                assert await session.scalar(select(func.count()).select_from(model)) == 0
        result = await service.accept_order(
            A, "same-key", CreateOrder.model_validate(create_payload), valid
        )
        assert not result.replayed

    asyncio.run(exercise())


def test_concurrent_winner_replays_even_if_the_other_catalog_read_fails(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        service = OrderPersistence(order_runtime_store["sessions"])

        async def loader():
            await accept(order_runtime_store, create_payload, quote_payload, key="overlap")
            raise RuntimeError("Catalog lost response")

        result = await service.accept_order(
            A, "overlap", CreateOrder.model_validate(create_payload), loader
        )
        assert result.replayed

    asyncio.run(exercise())


async def ready_order(store, payload, quote_payload):
    result = await accept(store, payload, quote_payload)
    order_id = UUID(result.body["orderId"])
    async with store["sessions"].begin() as session:
        row = await session.get(OrderRecord, order_id)
        workflow = await session.get(OrderWorkflow, order_id)
        row.status = OrderStatus.AWAITING_CONFIRMATION
        row.payment_status = PaymentStatus.AWAITING_COLLECTION
        workflow.phase, workflow.state = WorkflowPhase.IDLE, WorkflowState.DONE
        workflow.stock_step = StockStep.RESERVED
    return order_id


def test_actions_replay_before_state_checks_and_different_actions_recheck_locked_state(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        order_id = await ready_order(order_runtime_store, create_payload, quote_payload)
        service = OrderPersistence(order_runtime_store["sessions"])
        applied = 0

        async def confirm(session, locked):
            nonlocal applied
            applied += 1
            locked.order.status = OrderStatus.PREPARING
            session.add(
                OrderStatusHistory(
                    order_id=order_id,
                    from_status=OrderStatus.AWAITING_CONFIRMATION,
                    to_status=OrderStatus.PREPARING,
                    actor_type=HistoryActorType.ADMIN,
                    actor_id=ADMIN.user_id,
                    correlation_id=locked.workflow.correlation_id,
                )
            )
            return StoredResponse(
                200, {"orderId": str(order_id), "status": "PREPARING", "workflowState": "DONE"}
            )

        async def submit():
            return await service.accept_action(
                ADMIN, order_id, OrderAction.CONFIRM, "confirm-key", None, confirm
            )

        responses = await asyncio.wait_for(asyncio.gather(submit(), submit()), timeout=15)
        assert sum(x.replayed for x in responses) == 1 and applied == 1
        with pytest.raises(OrderRuleViolation, match="ORDER_STATE_CONFLICT"):
            await service.accept_action(
                ADMIN, order_id, OrderAction.CONFIRM, "new-key", None, confirm
            )
        with pytest.raises(OrderRuleViolation, match="NOT_FOUND"):
            await service.accept_action(
                B, order_id, OrderAction.CANCEL, "cancel", Reason(reason="wrong owner"), confirm
            )
        async with order_runtime_store["sessions"]() as session:
            assert await session.scalar(select(func.count()).select_from(OrderActionRequest)) == 1
            row = await session.get(OrderRecord, order_id)
            assert row.version == 1

    asyncio.run(exercise())


def test_action_failure_rolls_back_and_changed_reason_conflicts(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        order_id = await ready_order(order_runtime_store, create_payload, quote_payload)
        service = OrderPersistence(order_runtime_store["sessions"])

        async def fail(session, locked):
            locked.order.status = OrderStatus.CANCELLING
            await session.flush()
            raise RuntimeError("before acceptance")

        with pytest.raises(RuntimeError):
            await service.accept_action(
                A, order_id, OrderAction.CANCEL, "cancel", Reason(reason="one"), fail
            )

        async def cancel(session, locked):
            locked.order.status = OrderStatus.CANCELLING
            locked.workflow.phase = WorkflowPhase.CANCELLATION
            locked.workflow.state = WorkflowState.WAITING
            return StoredResponse(
                202, {"orderId": str(order_id), "status": "CANCELLING", "workflowState": "WAITING"}
            )

        await service.accept_action(
            A, order_id, OrderAction.CANCEL, "cancel", Reason(reason="one"), cancel
        )
        with pytest.raises(OrderRuleViolation, match="IDEMPOTENCY_CONFLICT"):
            await service.accept_action(
                A, order_id, OrderAction.CANCEL, "cancel", Reason(reason="two"), cancel
            )

    asyncio.run(exercise())


def test_cancel_and_dispatch_compete_under_the_same_order_lock(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        order_id = await ready_order(order_runtime_store, create_payload, quote_payload)
        async with order_runtime_store["sessions"].begin() as session:
            row = await session.get(OrderRecord, order_id)
            row.status = OrderStatus.PREPARING
        service = OrderPersistence(order_runtime_store["sessions"])

        async def cancel(session, locked):
            locked.order.status = OrderStatus.CANCELLING
            locked.workflow.phase = WorkflowPhase.CANCELLATION
            locked.workflow.state = WorkflowState.WAITING
            return StoredResponse(202, {"status": "CANCELLING"})

        async def dispatch(session, locked):
            locked.workflow.phase = WorkflowPhase.DISPATCH
            locked.workflow.state = WorkflowState.WAITING
            locked.workflow.stock_step = StockStep.COMMIT_PENDING
            return StoredResponse(202, {"status": "PREPARING"})

        results = await asyncio.wait_for(
            asyncio.gather(
                service.accept_action(
                    ADMIN,
                    order_id,
                    OrderAction.CANCEL,
                    "cancel-race",
                    Reason(reason="cancel"),
                    cancel,
                ),
                service.accept_action(
                    ADMIN, order_id, OrderAction.DISPATCH, "dispatch-race", None, dispatch
                ),
                return_exceptions=True,
            ),
            timeout=15,
        )
        assert sum(isinstance(result, StoredResponse) for result in results) == 1
        conflict = next(result for result in results if isinstance(result, OrderRuleViolation))
        assert conflict.code == "ORDER_STATE_CONFLICT"
        async with order_runtime_store["sessions"]() as session:
            assert await session.scalar(select(func.count()).select_from(OrderActionRequest)) == 1

    asyncio.run(exercise())


def test_real_order_reads_and_gateway_enforce_scope_pagination_and_safe_views(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        a = await accept(order_runtime_store, create_payload, quote_payload, key="a-one")
        second = await accept(order_runtime_store, create_payload, quote_payload, key="a-two")
        b = await accept(order_runtime_store, create_payload, quote_payload, actor=B, key="b-one")
        async with order_runtime_store["sessions"].begin() as session:
            row = await session.get(OrderRecord, UUID(second.body["orderId"]))
            row.status = OrderStatus.REJECTED
            first = await session.get(OrderRecord, UUID(a.body["orderId"]))
            row.created_at = first.created_at  # Exercise id tie-breaking at equal timestamps.
        app = create_app(
            Settings(
                app_env="test",
                database_enabled=True,
                database_url=order_runtime_store["url"],
                db_ssl_mode="disable",
            )
        )

        async def principal(request: Request):
            actor = {"Bearer a": A, "Bearer b": B, "Bearer admin": ADMIN}.get(
                request.headers.get("authorization")
            )
            if actor is None:
                raise ServiceError(401, "AUTH_INVALID", "Test authentication required")
            return actor

        app.dependency_overrides[current_actor] = (
            principal  # Test-only; runtime has no mock token path.
        )
        gateway = create_gateway(
            GatewaySettings(app_env="test"), order_transport=httpx.ASGITransport(app=app)
        )
        async with app.router.lifespan_context(app), gateway.router.lifespan_context(gateway):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=gateway), base_url="http://test"
            ) as client:
                headers = {
                    "Authorization": "Bearer a",
                    "X-User-Id": str(B.user_id),
                    "X-Role": "ADMIN",
                }
                first = await client.get("/api/v1/orders?pageSize=1", headers=headers)
                next_page = await client.get("/api/v1/orders?pageSize=1&page=2", headers=headers)
                assert first.status_code == 200 and first.json()["total"] == 2
                assert first.json()["items"][0]["id"] != next_page.json()["items"][0]["id"]
                assert first.headers["cache-control"] == "no-store"
                detail = await client.get(f"/api/v1/orders/{a.body['orderId']}", headers=headers)
                assert (
                    detail.json()["customerId"] == str(A.user_id)
                    and detail.json()["totalAmount"] == "430000"
                )
                assert set(detail.json()["workflow"]) == {"phase", "state", "requiresAttention"}
                assert "payload" not in detail.text and "operationId" not in detail.text
                denied = await client.get(f"/api/v1/orders/{b.body['orderId']}", headers=headers)
                assert denied.status_code == 404 and "Địa chỉ" not in denied.text
                assert denied.json()["requestId"] == denied.headers["x-request-id"]
                assert (
                    await client.get("/api/v1/admin/orders", headers=headers)
                ).status_code == 403
                rejected = await client.get("/api/v1/orders?status=REJECTED", headers=headers)
                assert rejected.json()["total"] == 1
                all_orders = await client.get(
                    "/api/v1/admin/orders", headers={"Authorization": "Bearer admin"}
                )
                assert all_orders.json()["total"] == 3
                searched = await client.get(
                    f"/api/v1/admin/orders?q={a.body['orderNumber'].lower()}",
                    headers={"Authorization": "Bearer admin"},
                )
                assert searched.json()["total"] == 1
                for query in ("page=0", "pageSize=101", "page=x", "status=UNKNOWN"):
                    invalid = await client.get("/api/v1/orders?" + query, headers=headers)
                    assert (
                        invalid.status_code == 400 and invalid.json()["code"] == "VALIDATION_ERROR"
                    )
                assert (
                    await client.get("/api/v1/orders", headers={"X-Role": "ADMIN"})
                ).status_code == 401
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://order"
                ) as direct:
                    private = await direct.get(
                        f"/api/v1/orders/{b.body['orderId']}", headers=headers
                    )
                    assert private.status_code == 404
                    assert (await direct.get("/api/v1/orders", headers=headers)).headers[
                        "cache-control"
                    ] == "no-store"

    asyncio.run(exercise())
