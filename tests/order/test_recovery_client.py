import asyncio
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from commerce_order.clients.recovery import InventorySnapshot, RecoveryUnavailable, SnapshotClient


def inventory_body(order_id):
    return {
        "orderId": str(order_id),
        "reservationId": str(uuid4()),
        "status": "RESERVED",
        "version": 1,
        "events": [],
    }


def test_recovery_client_uses_fixed_path_service_credential_and_bounded_json():
    async def exercise():
        order_id, correlation = uuid4(), uuid4()
        seen = []

        def endpoint(request):
            seen.append(request)
            return httpx.Response(200, json=inventory_body(order_id))

        async with httpx.AsyncClient(
            base_url="http://inventory.test", transport=httpx.MockTransport(endpoint)
        ) as http:
            client = SnapshotClient(
                http,
                SecretStr("test-internal-only"),
                InventorySnapshot,
                "/internal/reservations/by-order/",
            )
            assert (await client.get(order_id, correlation)).order_id == order_id
        assert seen[0].url.path == f"/internal/reservations/by-order/{order_id}"
        assert (
            seen[0].method == "GET"
            and seen[0].headers["authorization"] == "Bearer test-internal-only"
        )
        assert seen[0].headers["x-request-id"] == str(correlation)
        assert "cookie" not in seen[0].headers and "x-role" not in seen[0].headers

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "failure",
    [
        "timeout",
        "redirect",
        "unauthorized",
        "json",
        "wrong-order",
        "bool-version",
        "oversized",
        "missing-token",
    ],
)
def test_invalid_recovery_response_is_sanitized(failure):
    async def exercise():
        order_id = uuid4()

        def endpoint(request):
            if failure == "missing-token":
                pytest.fail("Unconfigured client must not contact dependency")
            if failure == "timeout":
                raise httpx.ReadTimeout("private-secret", request=request)
            if failure == "redirect":
                return httpx.Response(302, headers={"Location": "http://private.example"})
            if failure == "unauthorized":
                return httpx.Response(403, text="private-secret")
            if failure == "json":
                return httpx.Response(200, text="private-secret")
            if failure == "oversized":
                return httpx.Response(200, content=b" " * 1048577)
            body = inventory_body(order_id)
            if failure == "wrong-order":
                body["orderId"] = str(uuid4())
            if failure == "bool-version":
                body["version"] = True
            return httpx.Response(200, json=body)

        async with httpx.AsyncClient(
            base_url="http://inventory.test",
            transport=httpx.MockTransport(endpoint),
            follow_redirects=False,
        ) as http:
            client = SnapshotClient(
                http,
                None if failure == "missing-token" else SecretStr("private-service-token"),
                InventorySnapshot,
                "/internal/reservations/by-order/",
            )
            with pytest.raises(RecoveryUnavailable) as error:
                await client.get(order_id, uuid4())
            assert "private" not in str(error.value)

    asyncio.run(exercise())


def test_not_found_is_unknown_not_a_fabricated_failure():
    async def exercise():
        async with httpx.AsyncClient(
            base_url="http://inventory.test",
            transport=httpx.MockTransport(lambda request: httpx.Response(404)),
        ) as http:
            client = SnapshotClient(
                http, SecretStr("test"), InventorySnapshot, "/internal/reservations/by-order/"
            )
            assert await client.get(uuid4(), uuid4()) is None

    asyncio.run(exercise())


def test_terminal_payment_snapshot_requires_original_receipt():
    from commerce_order.clients.recovery import PaymentSnapshot, receipts

    snapshot = PaymentSnapshot.model_validate(
        {
            "orderId": str(uuid4()),
            "paymentId": str(uuid4()),
            "status": "SUCCEEDED",
            "version": 1,
            "method": "SIMULATED",
            "amount": "430000",
            "currency": "VND",
            "operationId": None,
            "commandMessageId": None,
            "events": [],
        }
    )
    with pytest.raises(RecoveryUnavailable, match="RECOVERY_TERMINAL_PROOF_MISSING"):
        receipts(snapshot)
