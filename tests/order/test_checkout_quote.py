import asyncio
import copy
import json
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from commerce_backend_common.errors import ServiceError
from commerce_gateway.main import create_app as gateway_app
from commerce_gateway.settings import Settings as GatewaySettings
from commerce_order.api.dependencies import current_actor
from commerce_order.api.schemas import QuoteInput
from commerce_order.clients.catalog import MAX_BATCH_BYTES, CatalogClient
from commerce_order.domain.enums import ActorRole
from commerce_order.domain.money import PG_BIGINT_MAX
from commerce_order.domain.transitions import Actor
from commerce_order.main import create_app
from commerce_order.services.quote import QuoteService
from commerce_order.settings import Settings

PRODUCT = UUID("10000000-0000-4000-8000-000000000011")
CUSTOMER = Actor(UUID("10000000-0000-4000-8000-000000000001"), ActorRole.CUSTOMER)


def batch_product(product_id=PRODUCT, **changes):
    return {
        "id": str(product_id),
        "sku": "DEMO-MOUSE",
        "name": "Test mouse",
        "status": "ACTIVE",
        "priceAmount": "200000",
        "currency": "VND",
        "version": 3,
        **changes,
    }


def test_quote_maps_unordered_batch_and_uses_only_server_credential():
    async def exercise():
        other = uuid4()
        request_id = str(uuid4())
        seen = []

        def upstream(request):
            seen.append(request)
            return httpx.Response(
                200,
                json={
                    "items": [
                        batch_product(other, sku="SECOND", priceAmount="50000"),
                        batch_product(internalField="never-exposed"),
                    ]
                },
            )

        async with httpx.AsyncClient(
            base_url="http://catalog.test", transport=httpx.MockTransport(upstream)
        ) as http:
            catalog = CatalogClient(
                http, Settings(catalog_service_token="test-service").catalog_service_token
            )
            service = QuoteService(catalog, 30000)
            result = await service.quote(
                QuoteInput.model_validate(
                    {
                        "items": [
                            {"productId": str(PRODUCT), "quantity": 2},
                            {"productId": str(other), "quantity": 1},
                        ]
                    }
                ),
                request_id,
            )
        body = result.model_dump(mode="json")
        assert [item["productId"] for item in body["items"]] == [str(PRODUCT), str(other)]
        assert body["subtotalAmount"] == "450000" and body["totalAmount"] == "480000"
        assert body["shippingFeeAmount"] == "30000" and body["currency"] == "VND"
        assert body["quotedAt"].endswith("Z") and "never-exposed" not in json.dumps(body)
        assert len(seen) == 1
        sent = seen[0]
        assert sent.method == "POST" and sent.url == "http://catalog.test/internal/products/batch"
        assert json.loads(sent.content) == {"productIds": [str(PRODUCT), str(other)]}
        assert sent.headers["authorization"] == "Bearer test-service"
        assert sent.headers["x-request-id"] == request_id
        assert "cookie" not in sent.headers and "x-user-id" not in sent.headers

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "failure,expected",
    [
        ("missing", 404),
        ("draft", 404),
        ("discontinued", 404),
        ("duplicate-id", 503),
        ("unrequested-id", 503),
        ("duplicate-sku", 503),
        ("integer-money", 503),
        ("negative-money", 503),
        ("overflow-money", 503),
        ("currency", 503),
        ("version-bool", 503),
        ("version-overflow", 503),
        ("missing-name", 503),
        ("blank-name", 503),
        ("missing-items", 503),
        ("invalid-json", 503),
        ("oversized", 503),
        ("timeout", 503),
        ("redirect", 503),
        ("unauthorized", 503),
    ],
)
def test_catalog_rejects_unavailable_or_invalid_batch_without_leaking_data(failure, expected):
    async def exercise():
        other = uuid4()
        requested = [PRODUCT]
        products = [batch_product(name="private-product")]
        if failure == "missing":
            products = []
        elif failure in {"draft", "discontinued"}:
            products[0]["status"] = "DRAFT" if failure == "draft" else "DISCONTINUED"
        elif failure == "duplicate-id":
            products *= 2
        elif failure == "unrequested-id":
            products.append(batch_product(other, sku="OTHER"))
        elif failure == "duplicate-sku":
            requested.append(other)
            products.append(batch_product(other))
        elif failure in {"integer-money", "negative-money", "overflow-money"}:
            products[0]["priceAmount"] = {
                "integer-money": 200000,
                "negative-money": "-1",
                "overflow-money": str(PG_BIGINT_MAX + 1),
            }[failure]
        elif failure == "currency":
            products[0]["currency"] = "USD"
        elif failure in {"version-bool", "version-overflow"}:
            products[0]["version"] = True if failure == "version-bool" else 2147483648
        elif failure == "missing-name":
            products[0].pop("name")
        elif failure == "blank-name":
            products[0]["name"] = "   "

        def upstream(request):
            if failure == "timeout":
                raise httpx.ReadTimeout("private-service-secret", request=request)
            if failure == "redirect":
                return httpx.Response(302, headers={"Location": "http://private.example"})
            if failure == "unauthorized":
                return httpx.Response(401, text="private-service-secret")
            if failure == "invalid-json":
                return httpx.Response(200, text="private-service-secret")
            if failure == "oversized":
                return httpx.Response(200, content=b" " * (MAX_BATCH_BYTES + 1))
            return httpx.Response(
                200, json={} if failure == "missing-items" else {"items": products}
            )

        async with httpx.AsyncClient(
            base_url="http://catalog.test", transport=httpx.MockTransport(upstream)
        ) as http:
            catalog = CatalogClient(
                http, Settings(catalog_service_token="test-service").catalog_service_token
            )
            with pytest.raises(ServiceError) as error:
                await catalog.products(requested, str(uuid4()))
        assert error.value.status == expected
        public = error.value.public_message
        assert "private-" not in public and error.value.details is None

    asyncio.run(exercise())


@pytest.mark.parametrize("missing", ["credential", "fee"])
def test_missing_quote_configuration_never_calls_catalog(missing):
    async def exercise():
        def unexpected(request):
            pytest.fail("Unconfigured quote must not contact Catalog")

        async with httpx.AsyncClient(
            base_url="http://catalog.test", transport=httpx.MockTransport(unexpected)
        ) as http:
            token = (
                None
                if missing == "credential"
                else Settings(catalog_service_token="test").catalog_service_token
            )
            service = QuoteService(CatalogClient(http, token), None if missing == "fee" else 30000)
            with pytest.raises(ServiceError) as error:
                await service.quote(
                    QuoteInput.model_validate(
                        {"items": [{"productId": str(PRODUCT), "quantity": 1}]}
                    ),
                    str(uuid4()),
                )
            assert error.value.status == 503

    asyncio.run(exercise())


def test_quote_http_needs_no_database_and_overflow_is_rejected():
    price = "200000"
    seen = []

    def upstream(request):
        seen.append(request)
        return httpx.Response(200, json={"items": [batch_product(priceAmount=price)]})

    app = create_app(
        Settings(app_env="test", catalog_service_token="service-test", shipping_fee_amount=0),
        catalog_transport=httpx.MockTransport(upstream),
    )
    app.dependency_overrides[current_actor] = lambda: CUSTOMER
    payload = {"items": [{"productId": str(PRODUCT), "quantity": 2}]}
    with TestClient(app) as client:
        response = client.post("/api/v1/orders/quote", json=payload)
        assert response.status_code == 200 and response.json()["totalAmount"] == "400000"
        assert response.headers["cache-control"] == "no-store"
        assert app.state.database is None and app.state.broker is None
        invalid = copy.deepcopy(payload)
        invalid["items"] *= 2
        assert client.post("/api/v1/orders/quote", json=invalid).status_code == 400
        assert len(seen) == 1
        price = str(PG_BIGINT_MAX)
        overflow = client.post("/api/v1/orders/quote", json=payload)
        assert overflow.status_code == 400 and overflow.json()["code"] == "VALIDATION_ERROR"
    assert app.state.catalog_client.is_closed


@pytest.mark.parametrize("path", ["/api/v1/orders/quote", "/api/v1/orders"])
def test_checkout_auth_defaults_closed_and_admin_cannot_buy(path, create_payload):
    app = create_app(Settings(app_env="test"))
    payload = (
        create_payload
        if path.endswith("orders")
        else {"items": [{"productId": str(PRODUCT), "quantity": 1}]}
    )
    with TestClient(app) as client:
        spoof = {"X-Role": "CUSTOMER", "X-User-Id": str(CUSTOMER.user_id)}
        assert client.post(path, json=payload, headers=spoof).status_code == 401
        response = client.post(
            path, json=payload, headers={**spoof, "Authorization": "Bearer unverified"}
        )
        assert response.status_code == 503 and response.json()["code"] == "AUTH_UNAVAILABLE"
        app.dependency_overrides[current_actor] = lambda: Actor(uuid4(), ActorRole.ADMIN)
        assert client.post(path, json=payload).status_code == 403


@pytest.mark.parametrize("value", [True, 1.5, -1, "-1", "1e3", "", str(PG_BIGINT_MAX + 1)])
def test_fee_is_explicit_bounded_integer(value):
    assert Settings(app_env="test").shipping_fee_amount is None
    assert Settings(app_env="test", shipping_fee_amount="30000").shipping_fee_amount == 30000
    with pytest.raises(ValidationError):
        Settings(app_env="test", shipping_fee_amount=value)


def test_catalog_config_rejects_unsafe_origin_and_secret_without_echoing():
    for url in (
        "https://user:private-secret@catalog.test",
        "http://catalog.test/path",
        "http://catalog.test?q=1",
    ):
        with pytest.raises(ValidationError):
            Settings(app_env="test", catalog_base_url=url)
    with pytest.raises(ValidationError) as error:
        Settings(app_env="test", catalog_service_token="private-secret\r\nheader")
    assert "private-secret" not in str(error.value)


def test_gateway_posts_forward_json_and_key_and_keep_price_changed_quote(
    create_payload, quote_payload
):
    seen = []
    mode = "accepted"

    def upstream(request):
        seen.append(request)
        if mode == "changed":
            return httpx.Response(
                409,
                json={
                    "code": "PRICE_CHANGED",
                    "message": "Confirm new prices",
                    "requestId": "old",
                    "details": {"quote": quote_payload},
                    "internal": "hidden",
                },
            )
        return httpx.Response(
            202, json={"orderId": str(uuid4()), "orderNumber": "TEST", "status": "PROCESSING"}
        )

    app = gateway_app(
        GatewaySettings(app_env="test"), order_transport=httpx.MockTransport(upstream)
    )
    headers = {
        "Authorization": "Bearer customer-test",
        "Idempotency-Key": "keep-key",
        "X-Role": "ADMIN",
        "Cookie": "private",
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/orders?url=http://evil.test", json=create_payload, headers=headers
        )
        assert response.status_code == 202
        assert response.headers["cache-control"] == "no-store"
        assert seen[-1].url.path == "/api/v1/orders" and not seen[-1].url.query
        assert json.loads(seen[-1].content) == create_payload
        assert seen[-1].headers["idempotency-key"] == "keep-key"
        assert seen[-1].headers["authorization"] == "Bearer customer-test"
        assert "x-role" not in seen[-1].headers and "cookie" not in seen[-1].headers
        mode = "changed"
        changed = client.post("/api/v1/orders", json=create_payload, headers=headers)
        assert changed.status_code == 409 and changed.json()["details"]["quote"] == quote_payload
        assert changed.json()["requestId"] == changed.headers["x-request-id"]
        assert "internal" not in changed.json()
        no_key = {"Authorization": "Bearer customer-test"}
        client.post("/api/v1/orders/quote", json={"items": []}, headers=no_key)
        assert (
            seen[-1].url.path == "/api/v1/orders/quote"
            and "idempotency-key" not in seen[-1].headers
        )
        before = len(seen)
        rejected = client.post(
            "/api/v1/orders", content="not json", headers={**headers, "Content-Type": "text/plain"}
        )
        assert rejected.status_code == 400 and len(seen) == before
