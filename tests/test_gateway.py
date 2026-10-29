from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from commerce_gateway.main import create_app
from commerce_gateway.settings import Settings


def test_fixed_upstream_and_client_cleanup():
    request_id = str(uuid4())
    seen = []

    def upstream(request):
        seen.append(request)
        return httpx.Response(
            200, json={"service": "catalog-service", "status": "alive", "checks": {}}
        )

    app = create_app(Settings(_env_file=None), transport=httpx.MockTransport(upstream))
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/health/catalog?url=http://evil.example",
            headers={
                "X-Request-Id": request_id,
                "Authorization": "Bearer do-not-forward",
            },
        )
        assert response.status_code == 200
        assert response.json()["service"] == "catalog-service"
        assert response.headers["x-request-id"] == request_id
    assert app.state.catalog_client.is_closed
    assert len(seen) == 1
    assert str(seen[0].url) == "http://127.0.0.1:3002/health/live"
    assert seen[0].headers["x-request-id"] == request_id
    assert "authorization" not in seen[0].headers


@pytest.mark.parametrize(
    "failure,status,code",
    [
        ("timeout", 504, "UPSTREAM_TIMEOUT"),
        ("connection", 503, "UPSTREAM_UNAVAILABLE"),
        ("http", 502, "UPSTREAM_ERROR"),
        ("json", 502, "UPSTREAM_INVALID_RESPONSE"),
        ("wrong-service", 502, "UPSTREAM_INVALID_RESPONSE"),
        ("redirect", 502, "UPSTREAM_ERROR"),
    ],
)
def test_upstream_failures_are_sanitized(failure, status, code):
    def upstream(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret-upstream", request=request)
        if failure == "connection":
            raise httpx.ConnectError("secret-upstream", request=request)
        if failure == "http":
            return httpx.Response(500, text="secret-upstream")
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "http://evil.example"})
        if failure == "json":
            return httpx.Response(200, text="secret-upstream")
        return httpx.Response(200, json={"service": "wrong", "status": "alive", "checks": {}})

    app = create_app(Settings(_env_file=None), transport=httpx.MockTransport(upstream))
    with TestClient(app) as client:
        response = client.get("/api/v1/health/catalog")
        assert response.status_code == status
        assert response.json()["code"] == code
        assert "secret-upstream" not in response.text


def test_gateway_to_actual_catalog_asgi():
    from commerce_catalog.main import create_app as create_catalog
    from commerce_catalog.settings import Settings as CatalogSettings

    catalog = create_catalog(CatalogSettings(_env_file=None))
    gateway = create_app(Settings(_env_file=None), transport=httpx.ASGITransport(app=catalog))
    with TestClient(catalog), TestClient(gateway) as client:
        assert client.get("/api/v1/health/catalog").json()["service"] == "catalog-service"
