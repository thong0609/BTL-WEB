import copy
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from commerce_gateway.main import create_app as gateway_app
from commerce_gateway.settings import Settings as GatewaySettings
from commerce_order.api.schemas import Complete, CreateOrder, Reason
from commerce_order.domain.enums import OrderAction
from commerce_order.main import create_app
from commerce_order.services.idempotency import action_hash, creation_hash, validate_key
from commerce_order.settings import Settings


def test_creation_hash_normalizes_defaults_money_uuid_text_and_item_order(create_payload):
    create_payload["note"] = ""
    first = CreateOrder.model_validate(create_payload)
    other = copy.deepcopy(create_payload)
    other.pop("note")
    other["recipient"]["name"] = "  " + other["recipient"]["name"] + "  "
    other["items"][0]["expectedUnitPriceAmount"] = "000200000"
    assert creation_hash(first) == creation_hash(CreateOrder.model_validate(other))
    other["items"].append({**other["items"][0], "productId": str(uuid4())})
    forward = creation_hash(CreateOrder.model_validate(other))
    other["items"].reverse()
    assert creation_hash(CreateOrder.model_validate(other)) == forward
    other["items"][0]["quantity"] += 1
    assert creation_hash(CreateOrder.model_validate(other)) != forward


def test_action_hash_includes_type_and_normalized_payload():
    reason = Reason.model_validate({"reason": "  đổi ý  "})
    assert action_hash(OrderAction.CANCEL, reason) == action_hash(
        OrderAction.CANCEL, Reason(reason="đổi ý")
    )
    assert action_hash(OrderAction.CANCEL, reason) != action_hash(
        OrderAction.RECORD_EXCEPTION, reason
    )
    assert action_hash(OrderAction.COMPLETE, Complete(delivered=True)) == action_hash(
        OrderAction.COMPLETE, Complete(delivered=True, codCollected=False)
    )
    with pytest.raises(ValueError):
        action_hash(OrderAction.CANCEL, None)
    with pytest.raises(ValueError):
        action_hash(OrderAction.DISPATCH, reason)
    for key in ("", "x" * 129):
        with pytest.raises(ValueError):
            validate_key(key)


@pytest.mark.parametrize("path", ["/api/v1/orders", "/api/v1/admin/orders"])
def test_runtime_auth_cannot_be_bypassed_by_identity_headers(path):
    app = create_app(Settings(app_env="test"))
    with TestClient(app) as client:
        spoofed = {"X-User-Id": str(uuid4()), "X-Role": "ADMIN"}
        assert client.get(path, headers=spoofed).status_code == 401
        response = client.get(path, headers={**spoofed, "Authorization": "Bearer unverified"})
        assert response.status_code == 503
        assert response.json()["code"] == "AUTH_UNAVAILABLE"


def test_gateway_fixed_order_route_forwards_only_allowed_headers_and_queries():
    seen = []

    def upstream(request):
        seen.append(request)
        return httpx.Response(200, json={"items": [], "page": 1, "pageSize": 20, "total": 0})

    app = gateway_app(
        GatewaySettings(app_env="test"), order_transport=httpx.MockTransport(upstream)
    )
    request_id = str(uuid4())
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/admin/orders?page=1&q=ORD&url=http://evil.example",
            headers={
                "Authorization": "Bearer original",
                "X-User-Id": "forged",
                "X-Role": "ADMIN",
                "Cookie": "session=private",
                "X-Request-Id": request_id,
                "Idempotency-Key": "keep",
            },
        )
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    sent = seen[0]
    assert sent.url.host == "127.0.0.1" and sent.url.port == 3004
    assert sent.url.path == "/api/v1/admin/orders" and dict(sent.url.params) == {
        "page": "1",
        "q": "ORD",
    }
    assert (
        sent.headers["authorization"] == "Bearer original"
        and sent.headers["x-request-id"] == request_id
    )
    assert sent.headers["idempotency-key"] == "keep"
    assert (
        "x-user-id" not in sent.headers
        and "x-role" not in sent.headers
        and "cookie" not in sent.headers
    )
    assert app.state.order_client.is_closed


@pytest.mark.parametrize(
    "failure,expected",
    [("timeout", 503), ("redirect", 502), ("invalid", 502), ("private-error", 502)],
)
def test_gateway_does_not_leak_invalid_upstream_data(failure, expected):
    def upstream(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private-token", request=request)
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "http://evil.example"})
        if failure == "private-error":
            return httpx.Response(500, text="private-token")
        return httpx.Response(200, text="private-token")

    app = gateway_app(
        GatewaySettings(app_env="test"), order_transport=httpx.MockTransport(upstream)
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/orders", headers={"Authorization": "Bearer original"})
        assert response.status_code == expected and "private-token" not in response.text


def test_gateway_rejects_missing_auth_and_untrusted_configured_origins():
    with TestClient(gateway_app(GatewaySettings(app_env="test"))) as client:
        assert client.get("/api/v1/orders", headers={"X-Role": "ADMIN"}).status_code == 401
    for url in (
        "https://user:secret@example.com",
        "https://example.com/path",
        "http://example.com?q=1",
    ):
        with pytest.raises(ValidationError):
            GatewaySettings(app_env="test", order_base_url=url)


@pytest.mark.parametrize("status", [401, 403, 404, 409, 429, 503])
def test_gateway_preserves_public_error_status_and_normalizes_request_id(status):
    def upstream(request):
        return httpx.Response(
            status,
            json={
                "code": "PUBLIC_CODE",
                "message": "Public error",
                "requestId": "upstream-id",
                "internal": "hidden",
            },
        )

    app = gateway_app(
        GatewaySettings(app_env="test"), order_transport=httpx.MockTransport(upstream)
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/orders", headers={"Authorization": "Bearer token"})
        assert response.status_code == status and response.json()["code"] == "PUBLIC_CODE"
        assert response.json()["requestId"] == response.headers["x-request-id"]
        assert "internal" not in response.json()
