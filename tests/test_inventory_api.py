"""INV-01 contract/auth checks and isolated PostgreSQL transaction/race checks."""

import asyncio
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from commerce_backend_common.errors import ServiceError
from commerce_inventory.main import create_app
from commerce_inventory.models import StockMovement
from commerce_inventory.settings import Settings
from commerce_inventory.upstreams import CatalogClient

ROOT = Path(__file__).resolve().parents[1]
BASE = "/api/v1/admin/inventory"
ACTOR = uuid4()


class Upstream:
    actor = ACTOR
    role = "ADMIN"
    status = "ACTIVE"
    identity_failure = None
    catalog_failure = None
    catalog_calls = 0
    requests = None

    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if request.url.path == "/api/v1/users/me":
            if self.identity_failure == "timeout":
                raise httpx.ReadTimeout("sensitive-test-error", request=request)
            if self.identity_failure:
                return httpx.Response(self.identity_failure, text="sensitive-test-error")
            return httpx.Response(
                200,
                json={
                    "id": str(self.actor),
                    "role": self.role,
                    "status": self.status,
                },
            )
        assert request.url.path == "/internal/products/batch"
        assert request.headers["authorization"] == "Bearer service-only"
        assert request.headers.get("x-request-id")
        self.catalog_calls += 1
        if self.catalog_failure == "timeout":
            raise httpx.ReadTimeout("sensitive-test-error", request=request)
        if self.catalog_failure == "malformed":
            return httpx.Response(200, json={"items": [{}]})
        if self.catalog_failure == "missing":
            return httpx.Response(200, json={"items": []})
        if self.catalog_failure == "wrong":
            return httpx.Response(200, json={"items": [{"id": str(uuid4())}]})
        if self.catalog_failure:
            return httpx.Response(self.catalog_failure, text="sensitive-test-error")
        product_id = json.loads(request.content)["productIds"][0]
        return httpx.Response(200, json={"items": [{"id": product_id}]})


HEADERS = {"Authorization": "Bearer admin-token"}


@pytest.mark.parametrize(
    "origin",
    [
        "http://remote.example",
        "https://user:password@example.com",
        "https://example.com/path",
        "https://example.com/?secret=1",
    ],
)
def test_upstream_origins_are_restricted(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, identity_base_url=origin)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, catalog_base_url=origin)


def test_catalog_requires_separate_service_credential():
    async def exercise():
        upstream = Upstream()
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as http:
            catalog = CatalogClient(http, Settings(_env_file=None), str(uuid4()))
            with pytest.raises(ServiceError) as error:
                await catalog.verify_product(uuid4())
            assert error.value.status == 503
            assert not upstream.requests

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", ""),
        ("post", "/items"),
        ("post", "/adjustments"),
        ("get", f"/{uuid4()}/movements"),
    ],
)
def test_inventory_requires_authentication(method, path):
    upstream = Upstream()
    app = create_app(Settings(_env_file=None), transport=httpx.MockTransport(upstream))
    with TestClient(app) as client:
        response = client.request(method, BASE + path, headers={"X-User-Role": "ADMIN"})
        assert response.status_code == 401
        assert response.json()["code"] == "AUTH_INVALID"
    assert not upstream.requests
    assert app.state.identity_client.is_closed
    assert app.state.catalog_client.is_closed


@pytest.mark.parametrize(
    "role,status,failure,expected",
    [
        ("CUSTOMER", "ACTIVE", None, 403),
        ("ADMIN", "DISABLED", None, 403),
        ("ADMIN", "ACTIVE", 401, 401),
        ("ADMIN", "ACTIVE", 500, 503),
        ("ADMIN", "ACTIVE", 302, 503),
        ("ADMIN", "ACTIVE", "timeout", 503),
    ],
)
def test_identity_verified_before_database(role, status, failure, expected):
    upstream = Upstream()
    upstream.role, upstream.status, upstream.identity_failure = role, status, failure
    app = create_app(Settings(_env_file=None), transport=httpx.MockTransport(upstream))
    with TestClient(app) as client:
        response = client.get(BASE, headers=HEADERS)
    assert response.status_code == expected
    assert "sensitive-test-error" not in response.text


@pytest.fixture(scope="module")
def inventory_database(postgres_test):
    password = quote(postgres_test["password"], safe="")
    port = postgres_test["port"]
    runtime_url = f"postgresql://inventory_runtime:{password}@127.0.0.1:{port}/commerce_test"
    env = {
        **postgres_test["env"],
        "DB_SSL_MODE": "disable",
        "SERVICE_NAME": "inventory-service",
        "DB_SCHEMA": "commerce_inventory",
        "DATABASE_URL": runtime_url,
        "MIGRATION_DATABASE_URL": (
            f"postgresql://inventory_migrator:{password}@127.0.0.1:{port}/commerce_test"
        ),
    }
    for arguments in [
        ["bootstrap", "--target", "test", "--apply"],
        ["upgrade", "--service", "inventory-service", "--apply"],
        ["check", "--service", "inventory-service"],
    ]:
        result = subprocess.run(
            [sys.executable, "scripts/database.py", *arguments],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert result.returncode == 0, result.stdout
    return {**postgres_test, "runtime_url": runtime_url}


def sql(database, statement, parameters=None):
    async def run():
        engine = create_async_engine(database["admin_url"], poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                result = await connection.execute(text(statement), parameters or {})
                return result.mappings().all() if result.returns_rows else None
        finally:
            await engine.dispose()

    return asyncio.run(run())


@pytest.fixture
def warehouse(inventory_database):
    database = inventory_database
    sql(
        database,
        "TRUNCATE commerce_inventory.stock_items, commerce_inventory.inventory_operations CASCADE",
    )
    upstream = Upstream()
    settings = Settings(
        _env_file=None,
        database_enabled=True,
        database_url=database["runtime_url"],
        db_ssl_mode="disable",
        catalog_service_token=SecretStr("service-only"),
    )
    app = create_app(settings, transport=httpx.MockTransport(upstream))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, upstream, database


def post(client, path, body, key=None):
    headers = {**HEADERS, "Idempotency-Key": key or str(uuid4())}
    return client.post(BASE + path, json=body, headers=headers)


def initialize(client, product_id=None, **kwargs):
    product_id = product_id or str(uuid4())
    response = post(client, "/items", {"productId": product_id, **kwargs})
    assert response.status_code == 201, response.text
    return product_id


@pytest.mark.integration
def test_initialize_replay_and_never_reset_stock(warehouse):
    client, upstream, database = warehouse
    product_id = str(uuid4())
    body = {"productId": product_id}
    first = post(client, "/items", body, "init-key")
    assert first.status_code == 201
    assert first.json()["onHandQuantity"] == 0
    adjustment = {"productId": product_id, "delta": 10, "reason": "Nhập hàng", "expectedVersion": 0}
    assert post(client, "/adjustments", adjustment).status_code == 200
    upstream.catalog_failure = "timeout"
    replay = post(client, "/items", body, "init-key")
    assert replay.json() == first.json()
    assert upstream.catalog_calls == 1
    upstream.catalog_failure = None
    current = post(client, "/items", body)
    assert current.json()["onHandQuantity"] == 10
    conflict = post(client, "/items", {**body, "lowStockThreshold": 8}, "init-key")
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    conflict = post(client, "/items", {**body, "lowStockThreshold": 8})
    assert conflict.json()["code"] == "STOCK_CONFIGURATION_CONFLICT"
    assert len(sql(database, "SELECT * FROM commerce_inventory.stock_items")) == 1


@pytest.mark.integration
def test_adjustment_replay_version_reserved_and_audit(warehouse):
    client, _, database = warehouse
    product_id = initialize(client)
    body = {"productId": product_id, "delta": 10, "reason": "Nhập hàng", "expectedVersion": 0}
    first = post(client, "/adjustments", body, "adjust-key")
    assert first.status_code == 200
    assert first.json()["onHandQuantity"] == 10
    assert first.json()["version"] == 1
    assert post(client, "/adjustments", body, "adjust-key").json() == first.json()
    conflict = post(client, "/adjustments", {**body, "delta": 11}, "adjust-key")
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    stale = post(client, "/adjustments", body)
    assert stale.json()["code"] == "STOCK_VERSION_CONFLICT"
    sql(
        database,
        "UPDATE commerce_inventory.stock_items SET reserved_quantity=3 WHERE product_id=:id",
        {"id": product_id},
    )
    below_reserved = {**body, "delta": -8, "expectedVersion": 1}
    rejected = post(client, "/adjustments", below_reserved, "rejected-key")
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "INSUFFICIENT_STOCK"
    valid = post(client, "/adjustments", {**body, "delta": 5, "expectedVersion": 1})
    assert valid.json()["onHandQuantity"] == 15
    # A rejected operation stays rejected after more stock arrives.
    assert (
        post(client, "/adjustments", below_reserved, "rejected-key").json()["code"]
        == "INSUFFICIENT_STOCK"
    )
    assert post(client, "/adjustments", body, "adjust-key").json() == first.json()
    movements = client.get(f"{BASE}/{product_id}/movements", headers=HEADERS).json()
    assert movements["total"] == 2
    assert movements["items"][0]["createdAt"].endswith("Z")
    audit = sql(database, "SELECT * FROM commerce_inventory.stock_movements")
    assert all(row["actor_id"] == ACTOR and row["actor_type"] == "USER" for row in audit)
    assert all(row["reason"] == "Nhập hàng" and row["reserved_delta"] == 0 for row in audit)


@pytest.mark.integration
@pytest.mark.parametrize(
    "failure,expected",
    [
        ("missing", 404),
        ("timeout", 503),
        ("malformed", 503),
        ("wrong", 503),
        (500, 503),
    ],
)
def test_catalog_failures_do_not_create_stock(warehouse, failure, expected):
    client, upstream, database = warehouse
    upstream.catalog_failure = failure
    body = {"productId": str(uuid4())}
    response = post(client, "/items", body, "catalog-key")
    assert response.status_code == expected
    assert "sensitive-test-error" not in response.text
    assert not sql(database, "SELECT * FROM commerce_inventory.stock_items")
    upstream.catalog_failure = None
    replay = post(client, "/items", body, "catalog-key")
    assert replay.status_code == (404 if failure == "missing" else 201)


@pytest.mark.integration
def test_pages_low_stock_and_movement_order(warehouse):
    client, _, _ = warehouse
    first = initialize(client)
    initialize(client, lowStockThreshold=0)
    post(
        client,
        "/adjustments",
        {"productId": first, "delta": 10, "reason": "Receipt", "expectedVersion": 0},
    )
    for delta, version in [(-1, 1), (-1, 2)]:
        response = post(
            client,
            "/adjustments",
            {
                "productId": first,
                "delta": delta,
                "reason": "Adjustment",
                "expectedVersion": version,
            },
        )
        assert response.status_code == 200
    response = client.get(BASE + "?page=1&pageSize=1", headers=HEADERS)
    assert response.json()["total"] == 2
    assert len(response.json()["items"]) == 1
    second_page = client.get(BASE + "?page=2&pageSize=1", headers=HEADERS).json()
    assert second_page["items"][0]["productId"] != response.json()["items"][0]["productId"]
    low = client.get(BASE + "?lowStock=true", headers=HEADERS).json()
    assert low["total"] == 1
    assert low["items"][0]["availableQuantity"] == 0
    high = client.get(BASE + "?lowStock=false", headers=HEADERS).json()
    assert high["total"] == 1 and high["items"][0]["productId"] == first
    history = client.get(f"{BASE}/{first}/movements?pageSize=1", headers=HEADERS).json()
    assert history["total"] == 3 and history["items"][0]["onHandAfter"] == 8
    missing = client.get(f"{BASE}/{uuid4()}/movements", headers=HEADERS)
    assert missing.status_code == 404


@pytest.mark.integration
def test_concurrent_adjustments_and_initialization(warehouse):
    client, _, database = warehouse
    product_id = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(
                lambda _: post(client, "/items", {"productId": product_id}, "same-init"), range(4)
            )
        )
    assert all(response.status_code == 201 for response in responses)
    body = {"productId": product_id, "delta": 10, "reason": "Receipt", "expectedVersion": 0}
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(lambda _: post(client, "/adjustments", body, "same-adjust"), range(4))
        )
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["onHandQuantity"] == 10 for response in responses)
    assert len(sql(database, "SELECT * FROM commerce_inventory.stock_movements")) == 1
    body = {**body, "expectedVersion": 1}
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: post(client, "/adjustments", body), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert len(sql(database, "SELECT * FROM commerce_inventory.stock_movements")) == 2


@pytest.mark.integration
def test_failed_movement_rolls_back_stock_and_operation(warehouse):
    client, _, database = warehouse
    product_id = initialize(client)

    def fail(*args):
        raise RuntimeError("sensitive-test-error")

    event.listen(StockMovement, "before_insert", fail)
    try:
        response = post(
            client,
            "/adjustments",
            {
                "productId": product_id,
                "delta": 5,
                "reason": "Receipt",
                "expectedVersion": 0,
            },
            "rollback-key",
        )
    finally:
        event.remove(StockMovement, "before_insert", fail)
    assert response.status_code == 500
    assert "sensitive-test-error" not in response.text
    rows = sql(database, "SELECT * FROM commerce_inventory.stock_items")
    assert rows[0]["on_hand_quantity"] == 0 and rows[0]["version"] == 0
    assert not sql(
        database,
        "SELECT * FROM commerce_inventory.inventory_operations WHERE operation_type='ADJUST'",
    )
    assert not sql(database, "SELECT * FROM commerce_inventory.stock_movements")
    assert (
        post(
            client,
            "/adjustments",
            {
                "productId": product_id,
                "delta": 5,
                "reason": "Receipt",
                "expectedVersion": 0,
            },
            "rollback-key",
        ).status_code
        == 200
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "patch",
    [
        {"delta": 0},
        {"delta": True},
        {"delta": "2"},
        {"reason": " "},
        {"expectedVersion": -1},
        {"reservedQuantity": 9},
    ],
)
def test_adjustment_validation(warehouse, patch):
    client, _, _ = warehouse
    body = {
        "productId": str(uuid4()),
        "delta": 1,
        "reason": "Receipt",
        "expectedVersion": 0,
        **patch,
    }
    assert post(client, "/adjustments", body).status_code == 400


@pytest.mark.integration
def test_missing_key_and_invalid_pagination(warehouse):
    client, _, _ = warehouse
    for key in (None, " ", "x" * 129):
        headers = dict(HEADERS)
        if key is not None:
            headers["Idempotency-Key"] = key
        response = client.post(BASE + "/items", json={"productId": str(uuid4())}, headers=headers)
        assert response.status_code == 400
    for query in ("page=0", "pageSize=101", "lowStock=invalid"):
        assert client.get(BASE + "?" + query, headers=HEADERS).status_code == 400


@pytest.mark.integration
def test_idempotency_is_scoped_to_actor_and_survives_restart(warehouse):
    client, upstream, database = warehouse
    first_product = initialize(client)
    body = {"productId": first_product, "delta": 3, "reason": "Receipt", "expectedVersion": 0}
    first = post(client, "/adjustments", body, "scoped-key")
    upstream.actor = uuid4()
    second_product = initialize(client)
    other = post(client, "/adjustments", {**body, "productId": second_product}, "scoped-key")
    assert first.status_code == other.status_code == 200
    settings = Settings(
        _env_file=None,
        database_enabled=True,
        database_url=database["runtime_url"],
        db_ssl_mode="disable",
        catalog_service_token=SecretStr("service-only"),
    )
    replacement = create_app(settings, transport=httpx.MockTransport(Upstream()))
    with TestClient(replacement) as restarted:
        replay = post(restarted, "/adjustments", body, "scoped-key")
        assert replay.json() == first.json()
    assert len(sql(database, "SELECT * FROM commerce_inventory.stock_movements")) == 2


@pytest.mark.integration
def test_gateway_to_inventory_uses_real_api_and_database(inventory_database):
    from commerce_gateway.main import create_app as create_gateway
    from commerce_gateway.settings import Settings as GatewaySettings

    async def exercise():
        settings = Settings(
            _env_file=None,
            database_enabled=True,
            database_url=inventory_database["runtime_url"],
            db_ssl_mode="disable",
            catalog_service_token=SecretStr("service-only"),
        )
        inventory = create_app(settings, transport=httpx.MockTransport(Upstream()))
        gateway = create_gateway(
            GatewaySettings(_env_file=None), transport=httpx.ASGITransport(app=inventory)
        )
        async with (
            inventory.router.lifespan_context(inventory),
            gateway.router.lifespan_context(gateway),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=gateway), base_url="http://test"
            ) as client,
        ):
            product_id = str(uuid4())
            headers = {**HEADERS, "Idempotency-Key": str(uuid4())}
            created = await client.post(
                BASE + "/items", headers=headers, json={"productId": product_id}
            )
            assert created.status_code == 201
            adjusted = await client.post(
                BASE + "/adjustments",
                headers=headers,
                json={
                    "productId": product_id,
                    "delta": 9,
                    "reason": "Receipt",
                    "expectedVersion": 0,
                },
            )
            assert adjusted.status_code == 200 and adjusted.json()["availableQuantity"] == 9
            history = await client.get(f"{BASE}/{product_id}/movements", headers=HEADERS)
            assert history.status_code == 200 and history.json()["total"] == 1
            denied = await client.get(BASE)
            assert denied.status_code == 401

    asyncio.run(exercise())
