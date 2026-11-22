import asyncio
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def http_examples():
    data = json.loads((ROOT / "docs/order/fixtures/http.json").read_text(encoding="utf-8"))
    return {example["name"]: example for example in data["examples"]}


@pytest.fixture
def create_payload(http_examples):
    return http_examples["create_cod"]["requestBody"]


@pytest.fixture
def quote_payload(http_examples):
    return http_examples["quote"]["responseBody"]


@pytest.fixture(scope="module")
def prepared_order_runtime(postgres_test):
    env = dict(postgres_test["env"])

    def run(*args):
        result = subprocess.run(
            [sys.executable, "scripts/database.py", *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    run("bootstrap", "--target", "test", "--apply")
    password = quote(postgres_test["password"], safe="")
    host = f"127.0.0.1:{postgres_test['port']}/commerce_test"
    runtime_url = f"postgresql+asyncpg://order_runtime:{password}@{host}"
    env.update(
        APP_ENV="test",
        SERVICE_NAME="order-service",
        DB_SCHEMA="commerce_orders",
        DB_SSL_MODE="disable",
        MIGRATION_DATABASE_URL=f"postgresql://order_migrator:{password}@{host}",
    )
    run("upgrade", "--service", "order-service", "--apply")
    return {"url": runtime_url, "admin_url": postgres_test["admin_url"]}


@pytest.fixture
def order_runtime_store(prepared_order_runtime):
    from commerce_order import models  # noqa: F401
    from commerce_order.db import Base

    async def clean():
        admin = create_async_engine(
            prepared_order_runtime["admin_url"],
            poolclass=NullPool,
            connect_args={"ssl": False},
            hide_parameters=True,
        )
        try:
            async with admin.begin() as connection:
                names = ", ".join(
                    f'commerce_orders."{table.name}"' for table in Base.metadata.sorted_tables
                )
                await connection.execute(text(f"TRUNCATE {names}"))
        finally:
            await admin.dispose()

    asyncio.run(clean())
    runtime = create_async_engine(
        prepared_order_runtime["url"],
        poolclass=NullPool,
        connect_args={"ssl": False},
        hide_parameters=True,
    )
    yield {
        "engine": runtime,
        "sessions": async_sessionmaker(runtime, expire_on_commit=False),
        "url": prepared_order_runtime["url"],
    }
    asyncio.run(runtime.dispose())
    asyncio.run(clean())
