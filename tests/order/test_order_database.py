"""Order schema and migrations on disposable PostgreSQL; no shared-dev URLs."""

import asyncio
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from commerce_order import models
from commerce_order.db import Base
from commerce_order.domain.enums import (
    OrderAction,
    OrderStatus,
    PaymentMethod,
    PaymentStep,
    StockStep,
    WorkflowPhase,
    WorkflowState,
)

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


def command(*args, env):
    result = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.fixture(scope="module")
def order_store(postgres_test):
    env = dict(postgres_test["env"])
    command("scripts/database.py", "bootstrap", "--target", "test", "--apply", env=env)
    port = postgres_test["port"]
    password = quote(postgres_test["password"], safe="")
    runtime_url = f"postgresql+asyncpg://order_runtime:{password}@127.0.0.1:{port}/commerce_test"
    env.update(
        APP_ENV="test",
        SERVICE_NAME="order-service",
        DB_SCHEMA="commerce_orders",
        DB_SSL_MODE="disable",
        DATABASE_URL=runtime_url,
        MIGRATION_DATABASE_URL=f"postgresql://order_migrator:{password}@127.0.0.1:{port}/commerce_test",
    )
    # Exercise an existing installation at the old revision, then upgrade it.
    command(
        "-m", "alembic", "-c", "apps/order-service/alembic.ini", "upgrade", "0001_base", env=env
    )
    command("scripts/database.py", "upgrade", "--service", "order-service", "--apply", env=env)
    command("scripts/database.py", "upgrade", "--service", "order-service", "--apply", env=env)
    command("scripts/database.py", "check", "--service", "order-service", env=env)
    command("scripts/database.py", "inspect", "--service", "order-service", env=env)
    yield {"env": env, "runtime_url": runtime_url, "admin_url": postgres_test["admin_url"]}


def engine(url):
    return create_async_engine(
        url, poolclass=NullPool, connect_args={"ssl": False}, hide_parameters=True
    )


@pytest.fixture(autouse=True)
def clean_order_tables(order_store):
    store = order_store

    async def clean():
        admin = engine(store["admin_url"])
        try:
            async with admin.begin() as connection:
                # Only Order's eight tables in the disposable commerce_test database.
                tables = ", ".join(
                    f'"commerce_orders"."{t.name}"' for t in Base.metadata.sorted_tables
                )
                await connection.execute(text(f"TRUNCATE {tables}"))
        finally:
            await admin.dispose()

    asyncio.run(clean())
    yield
    asyncio.run(clean())


def order_values(**changes):
    return {
        "id": uuid4(),
        "order_number": "TEST-" + uuid4().hex[:20],
        "customer_id": uuid4(),
        "status": OrderStatus.PROCESSING,
        "payment_method": PaymentMethod.COD,
        "recipient_name": "Khách thử",
        "recipient_phone": "0900000001",
        "shipping_address": "Địa chỉ giả lập dùng cho kiểm thử",
        "subtotal_amount": 400000,
        "shipping_fee_amount": 30000,
        "total_amount": 430000,
        **changes,
    }


async def persist_snapshot(session):
    values = order_values()
    order = models.OrderRecord(**values)
    session.add(order)
    await session.flush()  # Parent first; IDs are available for the remaining records.
    correlation = uuid4()
    session.add_all(
        [
            models.OrderItem(
                order_id=order.id,
                product_id=uuid4(),
                product_sku="DEMO-MOUSE",
                product_name="Chuột thử",
                catalog_version=3,
                unit_price_amount=200000,
                quantity=2,
                line_total_amount=400000,
            ),
            models.OrderStatusHistory(
                order_id=order.id,
                from_status=None,
                to_status=OrderStatus.PROCESSING,
                actor_type=models.HistoryActorType.SYSTEM,
                correlation_id=correlation,
            ),
            models.OrderWorkflow(
                order_id=order.id,
                phase=WorkflowPhase.CHECKOUT,
                state=WorkflowState.WAITING,
                stock_step=StockStep.RESERVE_PENDING,
                payment_step=PaymentStep.NOT_REQUESTED,
                correlation_id=correlation,
                reserve_operation_id=uuid4(),
            ),
            models.IdempotencyRequest(
                customer_id=order.customer_id,
                scope="CREATE_ORDER",
                idempotency_key="create-1",
                request_hash="a" * 64,
                order_id=order.id,
                response_status=202,
                response_body={"orderId": str(order.id), "status": "PROCESSING"},
            ),
            models.OutboxMessage(
                message_type="ReserveStock",
                aggregate_type="ORDER",
                aggregate_id=order.id,
                exchange_name="commerce.commands",
                routing_key="inventory.reserve",
                correlation_id=correlation,
                payload={"orderId": str(order.id), "operationId": str(uuid4())},
            ),
            models.ProcessedMessage(
                consumer_name="order-test",
                message_id=uuid4(),
                message_type="StockReserved",
                message_version=1,
                payload_hash="b" * 64,
                correlation_id=correlation,
            ),
        ]
    )
    await session.flush()
    return order


def test_upgrade_roundtrip_all_tables_and_atomic_rollback(order_store):
    async def exercise():
        runtime = engine(order_store["runtime_url"])
        sessions = async_sessionmaker(runtime, expire_on_commit=False)
        try:
            async with sessions() as session:
                async with session.begin():
                    order = await persist_snapshot(session)
                    # Replay records are storage primitives; no HTTP action is implemented here.
                    session.add(
                        models.OrderActionRequest(
                            order_id=order.id,
                            actor_id=uuid4(),
                            action=OrderAction.CANCEL,
                            idempotency_key="action-1",
                            request_hash="c" * 64,
                            response_status=202,
                            response_body={"orderId": str(order.id), "status": "CANCELLING"},
                        )
                    )
                assert order.created_at.tzinfo is not None
                assert order.total_amount == 430000 and order.version == 0
                workflow = await session.get(models.OrderWorkflow, order.id)
                assert workflow.reservation_id is None
                workflow.reservation_id = uuid4()  # Logical external UUID, no Inventory FK.
                await session.commit()
                item = await session.scalar(select(models.OrderItem))
                assert item.product_sku == "DEMO-MOUSE" and item.unit_price_amount == 200000
                record = await session.scalar(select(models.OutboxMessage))
                assert record.status == models.OutboxStatus.PENDING and record.attempt_count == 0
                assert record.payload["orderId"] == str(order.id)
            async with runtime.connect() as connection:
                for table in Base.metadata.sorted_tables:
                    assert (
                        await connection.scalar(
                            text(f'SELECT count(*) FROM commerce_orders."{table.name}"')
                        )
                        == 1
                    )
            with pytest.raises(RuntimeError, match="rollback"):
                async with sessions.begin() as session:
                    await persist_snapshot(session)
                    raise RuntimeError("force rollback")
            async with runtime.connect() as connection:
                for table in Base.metadata.sorted_tables:
                    assert (
                        await connection.scalar(
                            text(f'SELECT count(*) FROM commerce_orders."{table.name}"')
                        )
                        == 1
                    )
        finally:
            await runtime.dispose()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "changes",
    [
        {"subtotal_amount": -1, "total_amount": 29999},
        {"total_amount": 429999},
        {"shipping_fee_amount": -1, "total_amount": 399999},
        {"currency": "USD"},
        {"status": "UNKNOWN"},
        {"payment_method": "CARD"},
        {"payment_status": "UNKNOWN"},
        {"payment_version": -1},
        {"version": -1},
        {"recipient_name": None},
        {"total_amount": 9223372036854775808},
    ],
)
def test_postgres_rejects_invalid_order_data_itself(order_store, changes):
    async def exercise():
        runtime = engine(order_store["runtime_url"])
        try:
            values = order_values(**changes)
            # Raw SQL bypasses Python enum/domain checks to prove the DB constraints.
            columns = ", ".join(values)
            parameters = ", ".join(":" + name for name in values)
            with pytest.raises(DBAPIError):
                async with runtime.begin() as connection:
                    await connection.execute(
                        text(
                            f"INSERT INTO commerce_orders.orders ({columns}) VALUES ({parameters})"
                        ),
                        values,
                    )
        finally:
            await runtime.dispose()

    asyncio.run(exercise())


def test_scoped_keys_foreign_keys_and_inbox_primary_key(order_store):
    async def exercise():
        runtime = engine(order_store["runtime_url"])
        try:
            parent = order_values()
            async with runtime.begin() as connection:
                await connection.execute(insert(models.OrderRecord), parent)
            key = dict(
                customer_id=parent["customer_id"],
                scope="CREATE_ORDER",
                idempotency_key="same-key",
                request_hash="a" * 64,
                order_id=parent["id"],
                response_status=202,
                response_body={},
            )
            async with runtime.begin() as connection:
                await connection.execute(insert(models.IdempotencyRequest), key)
            with pytest.raises(IntegrityError):
                async with runtime.begin() as connection:
                    await connection.execute(insert(models.IdempotencyRequest), key)
            async with runtime.begin() as connection:
                await connection.execute(
                    insert(models.IdempotencyRequest), {**key, "customer_id": uuid4()}
                )
            with pytest.raises(IntegrityError):
                async with runtime.begin() as connection:
                    await connection.execute(
                        insert(models.IdempotencyRequest),
                        {**key, "idempotency_key": "different", "order_id": uuid4()},
                    )
            message = dict(
                consumer_name="consumer-a",
                message_id=uuid4(),
                message_type="StockReserved",
                message_version=1,
                payload_hash="d" * 64,
                correlation_id=uuid4(),
            )
            async with runtime.begin() as connection:
                await connection.execute(insert(models.ProcessedMessage), message)
                await connection.execute(
                    insert(models.ProcessedMessage), {**message, "consumer_name": "consumer-b"}
                )
            with pytest.raises(IntegrityError):
                async with runtime.begin() as connection:
                    await connection.execute(insert(models.ProcessedMessage), message)
        finally:
            await runtime.dispose()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": 0},
        {"quantity": 1000},
        {"line_total_amount": 1},
        {"catalog_version": -1},
    ],
)
def test_item_constraints_are_enforced_in_postgres(order_store, change):
    async def exercise():
        runtime = engine(order_store["runtime_url"])
        try:
            parent = order_values()
            async with runtime.begin() as connection:
                await connection.execute(insert(models.OrderRecord), parent)
            item = dict(
                order_id=parent["id"],
                product_id=uuid4(),
                product_sku="SKU-1",
                product_name="Test",
                catalog_version=1,
                unit_price_amount=200000,
                quantity=2,
                line_total_amount=400000,
            )
            with pytest.raises(IntegrityError):
                async with runtime.begin() as connection:
                    await connection.execute(insert(models.OrderItem), {**item, **change})
        finally:
            await runtime.dispose()

    asyncio.run(exercise())


def test_history_is_append_only_and_runtime_cannot_escape_schema(order_store):
    async def exercise():
        runtime = engine(order_store["runtime_url"])
        sessions = async_sessionmaker(runtime, expire_on_commit=False)
        try:
            async with sessions.begin() as session:
                await persist_snapshot(session)
            forbidden = [
                "UPDATE commerce_orders.order_status_history SET reason = 'rewritten'",
                "DELETE FROM commerce_orders.order_status_history",
                "UPDATE commerce_orders.alembic_version SET version_num = 'forged'",
                "CREATE TABLE commerce_orders.illegal_probe (id integer)",
                "TRUNCATE commerce_orders.orders CASCADE",
                "SELECT * FROM commerce_inventory.alembic_version",
            ]
            for statement in forbidden:
                with pytest.raises(DBAPIError):
                    async with runtime.begin() as connection:
                        await connection.execute(text(statement))
            async with runtime.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM commerce_orders.order_status_history")
                    )
                    == 1
                )
        finally:
            await runtime.dispose()

    asyncio.run(exercise())


def test_downgrade_and_reupgrade_preserve_other_schemas(order_store):
    marker = "step4_" + uuid4().hex[:12]

    async def sentinel(create):
        admin = engine(order_store["admin_url"])
        try:
            async with admin.begin() as connection:
                for schema in ("public", "commerce_inventory"):
                    if create:
                        await connection.execute(
                            text(f'CREATE TABLE "{schema}"."{marker}" (value integer)')
                        )
                        await connection.execute(
                            text(f'INSERT INTO "{schema}"."{marker}" VALUES (7)')
                        )
                    else:
                        assert (
                            await connection.scalar(
                                text(f'SELECT value FROM "{schema}"."{marker}"')
                            )
                            == 7
                        )
                if not create:
                    assert (
                        await connection.scalar(
                            text(
                                "SELECT count(*) FROM information_schema.tables "
                                "WHERE table_schema='commerce_orders' "
                                "AND table_name <> 'alembic_version'"
                            )
                        )
                        == 0
                    )
                    assert await connection.scalar(
                        text(
                            "SELECT to_regprocedure("
                            "'commerce_orders.reject_status_history_mutation()') IS NULL"
                        )
                    )
        finally:
            await admin.dispose()

    asyncio.run(sentinel(True))
    try:
        command(
            "-m",
            "alembic",
            "-c",
            "apps/order-service/alembic.ini",
            "downgrade",
            "0001_base",
            env=order_store["env"],
        )
        asyncio.run(sentinel(False))
    finally:
        command(
            "scripts/database.py",
            "upgrade",
            "--service",
            "order-service",
            "--apply",
            env=order_store["env"],
        )
    command("scripts/database.py", "check", "--service", "order-service", env=order_store["env"])

    async def cleanup_markers():
        admin = engine(order_store["admin_url"])
        try:
            async with admin.begin() as connection:
                for schema in ("public", "commerce_inventory"):
                    assert (
                        await connection.scalar(text(f'SELECT value FROM "{schema}"."{marker}"'))
                        == 7
                    )
                    await connection.execute(text(f'DROP TABLE "{schema}"."{marker}"'))
        finally:
            await admin.dispose()

    asyncio.run(cleanup_markers())
