import asyncio
import copy
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from commerce_gateway.main import create_app as create_gateway
from commerce_gateway.settings import Settings as GatewaySettings
from commerce_order.api.dependencies import current_actor
from commerce_order.domain.enums import ActorRole, OrderStatus
from commerce_order.domain.transitions import Actor
from commerce_order.main import create_app
from commerce_order.models import (
    IdempotencyRequest,
    OrderActionRequest,
    OrderItem,
    OrderRecord,
    OrderStatusHistory,
    OrderWorkflow,
    OutboxMessage,
    ProcessedMessage,
)
from commerce_order.services.persistence import OrderPersistence
from commerce_order.settings import Settings

pytestmark = pytest.mark.integration
CUSTOMER = Actor(UUID("10000000-0000-4000-8000-000000000001"), ActorRole.CUSTOMER)
TABLES = (
    OrderRecord,
    OrderItem,
    OrderWorkflow,
    OrderStatusHistory,
    IdempotencyRequest,
    OutboxMessage,
    OrderActionRequest,
    ProcessedMessage,
)


class CatalogStub:
    """Transport fixture only: the real Catalog batch handler is still pending."""

    def __init__(self, quote_payload):
        item = quote_payload["items"][0]
        self.product = {
            "id": item["productId"],
            "sku": item["sku"],
            "name": item["name"],
            "status": "ACTIVE",
            "priceAmount": item["unitPriceAmount"],
            "currency": "VND",
            "version": item["catalogVersion"],
        }
        self.failure = None
        self.seen = []

    def __call__(self, request):
        self.seen.append(request)
        if self.failure == "timeout":
            raise httpx.ReadTimeout("private-network-detail", request=request)
        if self.failure == "malformed":
            return httpx.Response(200, json={"items": [{"secret": "private-product"}]})
        return httpx.Response(
            200, json={"items": [] if self.failure == "missing" else [self.product]}
        )


def order_app(store, catalog):
    app = create_app(
        Settings(
            app_env="test",
            database_enabled=True,
            database_url=store["url"],
            db_ssl_mode="disable",
            catalog_service_token="order-to-catalog-test",
            shipping_fee_amount=30000,
        ),
        catalog_transport=httpx.MockTransport(catalog),
    )
    app.dependency_overrides[current_actor] = lambda: CUSTOMER
    return app


async def assert_counts(store, accepted):
    async with store["sessions"]() as session:
        for model in TABLES:
            expected = 0 if model in (OrderActionRequest, ProcessedMessage) else accepted
            assert await session.scalar(select(func.count()).select_from(model)) == expected, (
                model.__name__
            )


@pytest.mark.parametrize("payment_method", ["COD", "SIMULATED"])
def test_quote_create_snapshot_outbox_and_replay_without_catalog(
    order_runtime_store, create_payload, quote_payload, payment_method
):
    create_payload["paymentMethod"] = payment_method

    async def exercise():
        catalog = CatalogStub(quote_payload)
        app = order_app(order_runtime_store, catalog)
        request_id = str(uuid4())
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://order.test"
            ) as client,
        ):
            quoted = await client.post(
                "/api/v1/orders/quote",
                json={
                    "items": [{"productId": create_payload["items"][0]["productId"], "quantity": 2}]
                },
            )
            assert quoted.status_code == 200 and quoted.json()["totalAmount"] == "430000"
            await assert_counts(order_runtime_store, 0)
            headers = {
                "Idempotency-Key": "checkout-original",
                "X-Request-Id": request_id,
                "X-User-Id": str(uuid4()),
                "X-Role": "ADMIN",
            }
            accepted = await client.post("/api/v1/orders", json=create_payload, headers=headers)
            assert accepted.status_code == 202 and accepted.json()["status"] == "PROCESSING"
            assert accepted.headers["cache-control"] == "no-store"
            order_id = UUID(accepted.json()["orderId"])
            await assert_counts(order_runtime_store, 1)
            async with order_runtime_store["sessions"]() as session:
                record = await session.get(OrderRecord, order_id)
                workflow = await session.get(OrderWorkflow, order_id)
                history = await session.scalar(select(OrderStatusHistory))
                item = await session.scalar(select(OrderItem))
                outbox = await session.scalar(select(OutboxMessage))
                assert record.customer_id == CUSTOMER.user_id and record.total_amount == 430000
                assert record.payment_method == payment_method
                assert record.recipient_name == create_payload["recipient"]["name"]
                assert record.customer_note == create_payload["note"] and record.payment_id is None
                assert (
                    item.product_name == catalog.product["name"]
                    and item.unit_price_amount == 200000
                )
                assert item.catalog_version == 3 and item.quantity == 2
                assert workflow.phase == "CHECKOUT" and workflow.state == "WAITING"
                assert (
                    workflow.stock_step == "RESERVE_PENDING"
                    and workflow.payment_step == "NOT_REQUESTED"
                )
                assert workflow.reserve_operation_id is not None and workflow.reservation_id is None
                assert str(workflow.correlation_id) == request_id == str(history.correlation_id)
                assert history.from_status is None and history.to_status == "PROCESSING"
                assert (
                    outbox.message_type == "ReserveStock"
                    and outbox.routing_key == "inventory.reserve"
                )
                assert str(outbox.correlation_id) == request_id
                assert outbox.payload == {
                    "orderId": str(order_id),
                    "operationId": str(workflow.reserve_operation_id),
                    "items": [{"productId": catalog.product["id"], "quantity": 2}],
                }
            # Simulate a lost response and later progress; replay uses the original receipt.
            async with order_runtime_store["sessions"]() as session, session.begin():
                record = await session.get(OrderRecord, order_id)
                record.status = OrderStatus.REJECTED
            catalog.failure = "timeout"
            app.state.quote_service.shipping_fee_amount = None
            before = len(catalog.seen)
            replay = await client.post("/api/v1/orders", json=create_payload, headers=headers)
            assert replay.status_code == 202 and replay.json() == accepted.json()
            assert len(catalog.seen) == before
            changed = copy.deepcopy(create_payload)
            changed["note"] = "A different purchase"
            conflict = await client.post("/api/v1/orders", json=changed, headers=headers)
            assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
            assert len(catalog.seen) == before
            detail = await client.get(f"/api/v1/orders/{order_id}")
            assert detail.status_code == 200 and detail.json()["status"] == "REJECTED"
            assert detail.json()["totalAmount"] == "430000"
            await assert_counts(order_runtime_store, 1)

    asyncio.run(exercise())


@pytest.mark.parametrize("change", ["price", "version", "fee"])
def test_price_changed_returns_new_quote_via_gateway_without_reserving_key(
    order_runtime_store, create_payload, quote_payload, change
):
    async def exercise():
        catalog = CatalogStub(quote_payload)
        app = order_app(order_runtime_store, catalog)
        if change == "price":
            catalog.product["priceAmount"] = "250000"
        elif change == "version":
            catalog.product["version"] = 4
        gateway = create_gateway(
            GatewaySettings(app_env="test"), order_transport=httpx.ASGITransport(app)
        )
        async with (
            app.router.lifespan_context(app),
            gateway.router.lifespan_context(gateway),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(gateway), base_url="http://gateway.test"
            ) as client,
        ):
            if change == "fee":
                app.state.quote_service.shipping_fee_amount = 40000
            headers = {
                "Authorization": "Bearer test-only-dependency-override",
                "Idempotency-Key": "initial-key",
            }
            changed = await client.post("/api/v1/orders", json=create_payload, headers=headers)
            assert changed.status_code == 409 and changed.json()["code"] == "PRICE_CHANGED"
            assert changed.json()["requestId"] == changed.headers["x-request-id"]
            fresh = changed.json()["details"]["quote"]
            assert fresh["items"][0]["unitPriceAmount"] == catalog.product["priceAmount"]
            assert fresh["items"][0]["catalogVersion"] == catalog.product["version"]
            assert fresh["shippingFeeAmount"] == ("40000" if change == "fee" else "30000")
            await assert_counts(order_runtime_store, 0)
            confirmed = copy.deepcopy(create_payload)
            confirmed["items"][0]["expectedUnitPriceAmount"] = fresh["items"][0]["unitPriceAmount"]
            confirmed["items"][0]["expectedCatalogVersion"] = fresh["items"][0]["catalogVersion"]
            confirmed["expectedShippingFeeAmount"] = fresh["shippingFeeAmount"]
            headers["Idempotency-Key"] = "confirmed-new-key"
            accepted = await client.post("/api/v1/orders", json=confirmed, headers=headers)
            assert accepted.status_code == 202
            await assert_counts(order_runtime_store, 1)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "failure,status", [("missing", 404), ("inactive", 404), ("timeout", 503), ("malformed", 503)]
)
def test_catalog_failure_does_not_accept_order_and_same_key_can_retry(
    order_runtime_store, create_payload, quote_payload, failure, status
):
    async def exercise():
        catalog = CatalogStub(quote_payload)
        if failure == "inactive":
            catalog.product["status"] = "DISCONTINUED"
        else:
            catalog.failure = failure
        app = order_app(order_runtime_store, catalog)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://order.test"
            ) as client,
        ):
            headers = {"Idempotency-Key": "retry-after-catalog-error"}
            response = await client.post("/api/v1/orders", json=create_payload, headers=headers)
            assert response.status_code == status and "private-" not in response.text
            assert "details" not in response.json()
            await assert_counts(order_runtime_store, 0)
            catalog.failure = None
            catalog.product["status"] = "ACTIVE"
            accepted = await client.post("/api/v1/orders", json=create_payload, headers=headers)
            assert accepted.status_code == 202
            await assert_counts(order_runtime_store, 1)

    asyncio.run(exercise())


def test_invalid_create_body_and_key_have_no_catalog_or_database_effect(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        catalog = CatalogStub(quote_payload)
        app = order_app(order_runtime_store, catalog)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://order.test"
            ) as client,
        ):
            for headers in ({}, {"Idempotency-Key": ""}, {"Idempotency-Key": "x" * 129}):
                assert (
                    await client.post("/api/v1/orders", json=create_payload, headers=headers)
                ).status_code == 400
            for field, value in (
                ("customerId", str(uuid4())),
                ("totalAmount", "1"),
                ("simulationScenario", "SUCCESS"),
            ):
                invalid = {**create_payload, field: value}
                response = await client.post(
                    "/api/v1/orders", json=invalid, headers={"Idempotency-Key": "invalid"}
                )
                assert response.status_code == 400
            assert catalog.seen == []
            await assert_counts(order_runtime_store, 0)

    asyncio.run(exercise())


def test_database_failure_rolls_back_flushed_order_key_and_outbox(
    order_runtime_store, create_payload, quote_payload, monkeypatch
):
    async def exercise():
        original = OrderPersistence._write_order

        async def interrupted(self, *args, **kwargs):
            await original(self, *args, **kwargs)
            # All inserts have flushed, but the outer transaction has not committed.
            raise OperationalError(
                "test interrupted transaction", {}, Exception("private-storage-error")
            )

        catalog = CatalogStub(quote_payload)
        app = order_app(order_runtime_store, catalog)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://order.test"
            ) as client,
        ):
            monkeypatch.setattr(OrderPersistence, "_write_order", interrupted)
            headers = {"Idempotency-Key": "retry-after-storage-failure"}
            failed = await client.post("/api/v1/orders", json=create_payload, headers=headers)
            assert failed.status_code == 503 and failed.json()["code"] == "DEPENDENCY_UNAVAILABLE"
            assert "private-storage-error" not in failed.text
            await assert_counts(order_runtime_store, 0)
            monkeypatch.setattr(OrderPersistence, "_write_order", original)
            assert (
                await client.post("/api/v1/orders", json=create_payload, headers=headers)
            ).status_code == 202
            await assert_counts(order_runtime_store, 1)

    asyncio.run(exercise())


def test_concurrent_http_submissions_accept_one_order(
    order_runtime_store, create_payload, quote_payload
):
    async def exercise():
        both_called = asyncio.Event()
        calls = 0
        catalog = CatalogStub(quote_payload)

        async def concurrent_catalog(request):
            nonlocal calls
            calls += 1
            if calls == 2:
                both_called.set()
            await asyncio.wait_for(both_called.wait(), timeout=10)
            return catalog(request)

        app = order_app(order_runtime_store, concurrent_catalog)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://order.test"
            ) as client,
        ):
            responses = await asyncio.gather(
                *(
                    client.post(
                        "/api/v1/orders",
                        json=create_payload,
                        headers={"Idempotency-Key": "same-concurrent-key"},
                    )
                    for _ in range(2)
                )
            )
            assert all(response.status_code == 202 for response in responses)
            assert responses[0].json() == responses[1].json()
            await assert_counts(order_runtime_store, 1)

    asyncio.run(exercise())
