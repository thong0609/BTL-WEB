import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import BigInteger, DateTime, UniqueConstraint

from commerce_order import models
from commerce_order.db import SPEC, Base

TABLES = {
    "orders",
    "order_items",
    "order_status_history",
    "order_workflows",
    "idempotency_requests",
    "order_action_requests",
    "processed_messages",
    "outbox_messages",
}


def test_all_eight_tables_and_foreign_keys_belong_to_order():
    assert {table.name for table in Base.metadata.tables.values()} == TABLES
    for table in Base.metadata.tables.values():
        assert table.schema == SPEC.schema
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table.schema == SPEC.schema
    for column in (
        models.OrderRecord.__table__.c.customer_id,
        models.OrderRecord.__table__.c.payment_id,
        models.OrderItem.__table__.c.product_id,
        models.OrderWorkflow.__table__.c.reservation_id,
    ):
        assert not column.foreign_keys
    assert models.OrderWorkflow.__table__.c.reservation_id.nullable


def test_storage_types_preserve_integer_money_and_timezone():
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if column.name.endswith("_amount"):
                assert isinstance(column.type, BigInteger)
            if column.name.endswith("_at") or column.name == "locked_until":
                assert isinstance(column.type, DateTime) and column.type.timezone


def test_scoped_uniqueness_and_stable_pagination_indexes():
    expected = {
        models.IdempotencyRequest: {("customer_id", "scope", "idempotency_key")},
        models.OrderActionRequest: {("actor_id", "order_id", "action", "idempotency_key")},
        models.OrderItem: {("order_id", "product_id"), ("order_id", "product_sku")},
    }
    for model, keys in expected.items():
        actual = {
            tuple(constraint.columns.keys())
            for constraint in model.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert actual == keys
    indexes = {tuple(index.columns.keys()) for index in models.OrderRecord.__table__.indexes}
    assert indexes == {
        ("customer_id", "created_at", "id"),
        ("status", "created_at", "id"),
        ("created_at", "id"),
    }
    assert tuple(models.ProcessedMessage.__table__.primary_key.columns.keys()) == (
        "consumer_name",
        "message_id",
    )


def test_frozen_migration_generates_only_order_sql_without_connections_or_secrets():
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "APP_ENV": "test", "DB_SSL_MODE": "disable"}
    env["MIGRATION_DATABASE_URL"] = (
        "postgresql://order_migrator:offline-secret@127.0.0.1/commerce_test"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "apps/order-service/alembic.ini",
            "upgrade",
            "head",
            "--sql",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "offline-secret" not in result.stdout + result.stderr
    for name in TABLES:
        assert f"CREATE TABLE commerce_orders.{name}" in result.stdout
    assert "reservation_id UUID" in result.stdout
    assert "order_status_history_append_only" in result.stdout
    assert "CREATE SCHEMA" not in result.stdout and "CREATE TYPE" not in result.stdout
    for schema in (
        "public",
        "commerce_identity",
        "commerce_catalog",
        "commerce_inventory",
        "commerce_payments",
    ):
        assert f"CREATE TABLE {schema}." not in result.stdout
