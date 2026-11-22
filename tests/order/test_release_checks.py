import asyncio
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine
from test_worker_database import reserve, response

from commerce_order.api import schemas
from commerce_order.main import create_app
from commerce_order.messaging.inbox import InboxProcessor
from commerce_order.models import OrderRecord, OutboxMessage, ProcessedMessage
from commerce_order.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_public_order_contract_matches_runtime_request_response_fields_and_routes():
    document = yaml.safe_load((ROOT / "docs/contracts/openapi.yaml").read_text(encoding="utf-8"))
    for name in (
        "CartItem",
        "QuoteInput",
        "ConfirmedItem",
        "CreateOrder",
        "Recipient",
        "QuoteItem",
        "Quote",
        "OrderAccepted",
        "ActionResult",
        "Order",
        "OrderSummary",
        "OrderPage",
        "Reason",
        "Complete",
    ):
        runtime = getattr(schemas, name).model_json_schema(by_alias=True)
        contract = document["components"]["schemas"][name]
        assert set(runtime["properties"]) == set(contract["properties"]), name
        assert set(runtime.get("required", [])) == set(contract.get("required", [])), name
    runtime_paths = create_app(Settings(app_env="test")).openapi()["paths"]
    order_paths = {
        "/api/v1" + path: value
        for path, value in document["paths"].items()
        if path == "/orders" or path.startswith(("/orders/", "/admin/orders"))
    }
    assert sum(len(value) for value in order_paths.values()) == 12
    for path, methods in order_paths.items():
        for method, operation in methods.items():
            actual = runtime_paths[path][method]
            assert bool(operation.get("security")) and bool(actual.get("security"))
            assert {code for code in operation["responses"] if code.startswith("2")} == {
                code for code in actual["responses"] if code.startswith("2")
            }


@pytest.mark.integration
def test_order_backup_restore_keeps_inbox_outbox_and_resumes_pending_payment(
    order_runtime_store, postgres_test, create_payload, quote_payload
):
    store = order_runtime_store
    container = postgres_test["container"]
    assert container.startswith("commerce-db-test-")

    async def prepare():
        initial, payment, event = await reserve(store, create_payload, quote_payload)
        return initial.aggregate_id, payment, event

    order_id, command, event = asyncio.run(prepare())
    backup = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "pg_dump",
            "-U",
            "postgres",
            "-d",
            "commerce_test",
            "--format=custom",
            "--data-only",
            "--schema=commerce_orders",
            "--exclude-table=commerce_orders.alembic_version",
        ],
        capture_output=True,
        timeout=30,
        check=True,
    ).stdout
    assert len(backup) > 100

    async def empty_test_tables():
        from commerce_order.db import Base

        admin = create_async_engine(postgres_test["admin_url"], hide_parameters=True)
        try:
            async with admin.begin() as conn:
                tables = ", ".join(
                    f'commerce_orders."{t.name}"' for t in Base.metadata.sorted_tables
                )
                await conn.execute(text(f"TRUNCATE {tables}"))
        finally:
            await admin.dispose()

    asyncio.run(empty_test_tables())
    restored = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "pg_restore",
            "-U",
            "postgres",
            "-d",
            "commerce_test",
            "--data-only",
            "--no-owner",
            "--exit-on-error",
        ],
        input=backup,
        capture_output=True,
        timeout=30,
    )
    assert restored.returncode == 0, "Unable to restore isolated Order test backup"

    async def resume():
        inbox = InboxProcessor(store["sessions"])
        assert await inbox.process(event) == "duplicate"
        async with store["sessions"]() as session:
            assert await session.scalar(select(func.count()).select_from(OrderRecord)) == 1
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 2
            assert await session.scalar(select(func.count()).select_from(ProcessedMessage)) == 1
            payment = await session.get(OutboxMessage, command.id)
            assert payment.payload == command.payload
        result = response(
            command,
            "PaymentInitialized",
            paymentId=str(uuid4()),
            paymentVersion=1,
            paymentStatus="AWAITING_COLLECTION",
            method="COD",
            amount="430000",
            currency="VND",
        )
        assert await inbox.process(result) == "applied"
        assert await inbox.process(result) == "duplicate"
        async with store["sessions"]() as session:
            order = await session.get(OrderRecord, order_id)
            assert order.status.value == "AWAITING_CONFIRMATION"
            assert order.total_amount == 430000
            assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 2

    asyncio.run(resume())
