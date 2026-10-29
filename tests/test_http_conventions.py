import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from commerce_backend_common.application import build_app
from commerce_backend_common.schemas import ApiModel, MoneyAmount, UtcDatetime
from commerce_catalog.settings import Settings


class Payload(ApiModel):
    item_id: UUID
    amount: MoneyAmount
    occurred_at: UtcDatetime


def create_test_app():
    app = build_app(Settings(_env_file=None))

    @app.post("/probe", response_model=Payload)
    async def probe(payload: Payload) -> Payload:
        return payload

    @app.get("/denied")
    async def denied():
        raise HTTPException(
            401, detail="secret-auth-reason", headers={"WWW-Authenticate": "Bearer"}
        )

    @app.get("/broken")
    async def broken():
        raise RuntimeError("secret-database-credential")

    return app


def test_serialization_preserves_uuid_money_and_utc():
    item_id = uuid4()
    with TestClient(create_test_app()) as client:
        response = client.post(
            "/probe",
            json={
                "itemId": str(item_id),
                "amount": 9007199254740993,
                "occurredAt": "2026-10-28T19:00:00+07:00",
            },
        )
    assert response.status_code == 200
    assert response.json() == {
        "itemId": str(item_id),
        "amount": "9007199254740993",
        "occurredAt": "2026-10-28T12:00:00Z",
    }


@pytest.mark.parametrize("amount", [-1, 0.1, True, "2000"])
def test_invalid_money_is_rejected(amount):
    with pytest.raises(ValidationError):
        Payload(item_id=uuid4(), amount=amount, occurred_at=datetime.now(UTC))


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValidationError):
        Payload(item_id=uuid4(), amount=1, occurred_at=datetime(2026, 10, 28))


def test_validation_and_unexpected_errors_are_private(capsys):
    with TestClient(create_test_app()) as client:
        invalid = client.post("/probe", json={"itemId": "secret-value", "amount": "secret-value"})
        assert invalid.status_code == 400
        assert invalid.json()["code"] == "VALIDATION_ERROR"
        assert isinstance(invalid.json()["details"]["fields"], list)
        assert "secret-value" not in invalid.text
        denied = client.get("/denied")
        assert denied.status_code == 401
        assert denied.headers["www-authenticate"] == "Bearer"
        assert "secret-auth-reason" not in denied.text
        broken = client.get(
            "/broken?token=secret-query",
            headers={
                "Origin": "http://localhost:3100",
                "Authorization": "Bearer secret-token",
                "X-Request-Id": "untrusted-identifier",
            },
        )
        assert broken.status_code == 500
        assert broken.json()["code"] == "INTERNAL_ERROR"
        assert UUID(broken.json()["requestId"])
        assert broken.headers["access-control-allow-origin"] == "http://localhost:3100"
    logs = capsys.readouterr().out
    assert "secret-" not in logs
    events = [json.loads(line) for line in logs.splitlines() if line.strip()]
    assert any(e["event"] == "request_failed" for e in events)
    completed = [e for e in events if e["event"] == "request_completed"]
    assert all(e["service"] == "catalog-service" and "request_id" in e for e in completed)


def test_cors_explicit_origin_only():
    with TestClient(create_test_app()) as client:
        allowed = client.options(
            "/probe",
            headers={
                "Origin": "http://localhost:3100",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert allowed.status_code == 200
        blocked = client.options(
            "/probe",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert blocked.status_code == 400
        assert "access-control-allow-origin" not in blocked.headers


def test_concurrent_request_ids_do_not_leak(capsys):
    app = create_test_app()

    @app.get("/wait")
    async def wait(request: Request):
        await asyncio.sleep(0.01)
        return {"requestId": request.state.request_id}

    ids = [str(uuid4()), str(uuid4())]

    async def run():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await asyncio.gather(
                    *[client.get("/wait", headers={"X-Request-Id": value}) for value in ids]
                )

    responses = asyncio.run(run())
    assert [r.json()["requestId"] for r in responses] == ids
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    completed = [e for e in events if e["event"] == "request_completed"]
    assert {e["request_id"] for e in completed} == set(ids)
