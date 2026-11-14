import asyncio
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from commerce_backend_common.database import Database
from commerce_backend_common.messaging import MessageEnvelope
from commerce_payment.contracts import PaymentMessageError, command_hash, parse_command
from commerce_payment.db import SPEC
from commerce_payment.handling import handle_message, settle_due
from commerce_payment.models import DemoConfiguration, OutboxMessage, PaymentAttempt
from commerce_payment.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def test_payment_command_rejects_non_string_amount():
    envelope = _envelope(
        "ProcessPayment",
        {
            "orderId": str(uuid4()),
            "operationId": str(uuid4()),
            "customerId": str(uuid4()),
            "amount": 430000,
            "currency": "VND",
        },
    )
    with pytest.raises(PaymentMessageError) as failure:
        parse_command(envelope)
    assert failure.value.code == "INVALID_MESSAGE"


def test_payment_command_hash_ignores_key_order():
    operation_id = uuid4()
    order_id = uuid4()
    customer_id = uuid4()
    first = parse_command(
        _envelope(
            "InitializeCodPayment",
            {
                "amount": "430000",
                "currency": "VND",
                "customerId": str(customer_id),
                "operationId": str(operation_id),
                "orderId": str(order_id),
            },
        )
    )
    second = parse_command(
        _envelope(
            "InitializeCodPayment",
            {
                "orderId": str(order_id),
                "operationId": str(operation_id),
                "customerId": str(customer_id),
                "currency": "VND",
                "amount": "0430000",
            },
        )
    )
    assert command_hash(first) == command_hash(second)


@pytest.fixture(scope="module")
def payment_runtime_url(postgres_test):
    env = postgres_test["env"]
    password = quote(postgres_test["password"], safe="")
    port = postgres_test["port"]
    _database_command("bootstrap", "--target", "test", "--apply", env=env)
    service_env = dict(env)
    service_env.update(
        DB_SSL_MODE="disable",
        SERVICE_NAME="payment-service",
        DB_SCHEMA="commerce_payments",
        DATABASE_URL=(f"postgresql://payment_runtime:{password}@127.0.0.1:{port}/commerce_test"),
        MIGRATION_DATABASE_URL=(
            f"postgresql://payment_migrator:{password}@127.0.0.1:{port}/commerce_test"
        ),
    )
    _database_command("upgrade", "--service", "payment-service", "--apply", env=service_env)
    return f"postgresql+asyncpg://payment_runtime:{password}@127.0.0.1:{port}/commerce_test"


@pytest.mark.integration
def test_cod_payment_is_created_once(payment_runtime_url):
    async def exercise():
        order_id, customer_id, operation_id = uuid4(), uuid4(), uuid4()
        message = _cod(order_id, customer_id, operation_id, "430000")
        async with _database(payment_runtime_url) as database:
            async with database.session() as session:
                created = await handle_message(session, message, now=NOW)
                replayed = await handle_message(session, message, now=NOW)
                same_operation = await handle_message(
                    session, _cod(order_id, customer_id, operation_id, "430000"), now=NOW
                )
                conflict = await handle_message(
                    session, _cod(order_id, customer_id, operation_id, "1000"), now=NOW
                )
                other = await handle_message(
                    session, _cod(order_id, customer_id, uuid4(), "430000"), now=NOW
                )
            payment = await _payment(database, order_id)
            events = await _events(database, order_id)
        assert created.disposition == "applied"
        assert created.event_type == "PaymentInitialized"
        assert replayed.disposition == "replayed"
        assert replayed.event_type == "PaymentInitialized"
        assert same_operation.disposition == "replayed"
        assert same_operation.event_type == "PaymentInitialized"
        assert conflict.disposition == "rejected"
        assert other.disposition == "rejected"
        assert payment.status == "AWAITING_COLLECTION"
        assert payment.amount == 430000
        assert events.count("PaymentInitialized") == 1
        assert events.count("PaymentCommandRejected") == 2

    asyncio.run(exercise())


@pytest.mark.integration
def test_simulated_success_failure_and_delay(payment_runtime_url):
    async def exercise():
        async with _database(payment_runtime_url) as database:
            success = await _simulate(database, "SUCCESS", 0)
            failure = await _simulate(database, "FAILURE", 0)
            delayed = await _simulate(database, "DELAYED_SUCCESS", 60)
            async with database.session() as session:
                await settle_due(session, now=NOW)
                early = await _payment(database, delayed)
            async with database.session() as session:
                finished = await settle_due(session, now=NOW.replace(minute=1))
            late = await _payment(database, delayed)
            success_payment = await _payment(database, success)
            failure_payment = await _payment(database, failure)
        assert success_payment.status == "SUCCEEDED"
        assert failure_payment.status == "FAILED"
        assert failure_payment.failure_code == "SIMULATION_FAILURE"
        assert early.status == "PENDING"
        assert finished == 1
        assert late.status == "SUCCEEDED"

    asyncio.run(exercise())


@pytest.mark.integration
def test_cod_collection_and_cancel_happen_once(payment_runtime_url):
    async def exercise():
        async with _database(payment_runtime_url) as database:
            order_id, customer_id = uuid4(), uuid4()
            created = await _send(database, _cod(order_id, customer_id, uuid4(), "430000"))
            payment_id = created.payment_id
            assert payment_id is not None
            collector = uuid4()
            operation_id = uuid4()
            collected = await _send(
                database,
                _envelope(
                    "RecordCodCollection",
                    {
                        "orderId": str(order_id),
                        "operationId": str(operation_id),
                        "paymentId": str(payment_id),
                        "collectedBy": str(collector),
                    },
                ),
            )
            again = await _send(
                database,
                _envelope(
                    "RecordCodCollection",
                    {
                        "orderId": str(order_id),
                        "operationId": str(operation_id),
                        "paymentId": str(payment_id),
                        "collectedBy": str(collector),
                    },
                ),
            )
            duplicate = await _send(
                database,
                _envelope(
                    "RecordCodCollection",
                    {
                        "orderId": str(order_id),
                        "operationId": str(uuid4()),
                        "paymentId": str(payment_id),
                        "collectedBy": str(uuid4()),
                    },
                ),
            )
            payment = await _payment(database, order_id)
            events = await _events(database, order_id)
        assert collected.disposition == "applied"
        assert again.disposition == "replayed"
        assert again.event_type == "CodCollected"
        assert duplicate.disposition == "rejected"
        assert payment.status == "SUCCEEDED"
        assert payment.collected_by == collector
        assert events.count("CodCollected") == 1

        cancel_order, cancel_customer = uuid4(), uuid4()
        async with _database(payment_runtime_url) as database:
            opened = await _send(database, _cod(cancel_order, cancel_customer, uuid4(), "430000"))
            assert opened.payment_id is not None
            cancelled = await _send(
                database,
                _envelope(
                    "CancelCodPayment",
                    {
                        "orderId": str(cancel_order),
                        "operationId": str(uuid4()),
                        "paymentId": str(opened.payment_id),
                        "reason": "Khách đổi ý",
                    },
                ),
            )
            refund_rejected = await _send(
                database,
                _envelope(
                    "RefundPayment",
                    {
                        "orderId": str(cancel_order),
                        "operationId": str(uuid4()),
                        "paymentId": str(opened.payment_id),
                        "amount": "430000",
                        "currency": "VND",
                        "reason": "Hoàn nhầm",
                    },
                ),
            )
            state = await _payment(database, cancel_order)
        assert cancelled.event_type == "CodPaymentCancelled"
        assert refund_rejected.disposition == "rejected"
        assert state.status == "CANCELLED"

    asyncio.run(exercise())


@pytest.mark.integration
def test_refund_matches_the_original_amount_and_retries_once(payment_runtime_url):
    async def exercise():
        async with _database(payment_runtime_url) as database:
            await _configure(database, refund_scenario="SUCCESS", delay_seconds=0)
            order_id = await _simulate(database, "SUCCESS", 0)
            payment = await _payment(database, order_id)
            mismatch = await _send(
                database,
                _refund(order_id, payment.id, uuid4(), "1000"),
            )
            refunded = await _send(
                database,
                _refund(order_id, payment.id, uuid4(), "430000"),
            )
            repeated = await _send(
                database,
                _refund(order_id, payment.id, uuid4(), "430000"),
            )
            paid = await _payment(database, order_id)
            events = await _events(database, order_id)
        assert mismatch.disposition == "rejected"
        assert refunded.event_type == "PaymentRefunded"
        assert repeated.disposition == "rejected"
        assert paid.status == "REFUNDED"
        assert events.count("PaymentRefunded") == 1

        async with _database(payment_runtime_url) as database:
            await _configure(database, refund_scenario="FAIL_UNTIL_RETRY", delay_seconds=0)
            retry_order = await _simulate(database, "SUCCESS", 0)
            retry_payment = await _payment(database, retry_order)
            failed = await _send(
                database, _refund(retry_order, retry_payment.id, uuid4(), "430000")
            )
            waiting = await _payment(database, retry_order)
            async with database.session() as session:
                settled = await settle_due(session, now=NOW)
            async with database.session() as session:
                settled_again = await settle_due(session, now=NOW)
            done = await _payment(database, retry_order)
            retry_events = await _events(database, retry_order)
        assert failed.event_type == "PaymentRefundFailed"
        assert waiting.status == "REFUND_PENDING"
        assert settled == 1
        assert settled_again == 0
        assert done.status == "REFUNDED"
        assert retry_events.count("PaymentRefunded") == 1
        assert retry_events.count("PaymentRefundFailed") == 1

    asyncio.run(exercise())


def _envelope(message_type, payload, message_id=None):
    return MessageEnvelope(
        message_id=message_id or uuid4(),
        type=message_type,
        version=1,
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=NOW,
        payload=payload,
    )


def _cod(order_id, customer_id, operation_id, amount, message_id=None):
    return _envelope(
        "InitializeCodPayment",
        {
            "orderId": str(order_id),
            "operationId": str(operation_id),
            "customerId": str(customer_id),
            "amount": amount,
            "currency": "VND",
        },
        message_id,
    )


def _refund(order_id, payment_id, operation_id, amount):
    return _envelope(
        "RefundPayment",
        {
            "orderId": str(order_id),
            "operationId": str(operation_id),
            "paymentId": str(payment_id),
            "amount": amount,
            "currency": "VND",
            "reason": "Hủy trước giao",
        },
    )


class _database:
    def __init__(self, url):
        self.url = url
        self.database = None

    async def __aenter__(self):
        self.database = Database(
            Settings(
                _env_file=None,
                app_env="test",
                database_enabled=True,
                db_ssl_mode="disable",
                database_url=self.url,
            ),
            SPEC,
        )
        return self.database

    async def __aexit__(self, *_args):
        if self.database is not None:
            await self.database.close()


async def _send(database, envelope):
    async with database.session() as session:
        return await handle_message(session, envelope, now=NOW)


async def _configure(database, *, payment_scenario=None, refund_scenario=None, delay_seconds=None):
    async with database.session() as session:
        async with session.begin():
            config = await session.get(DemoConfiguration, 1)
            assert config is not None
            if payment_scenario is not None:
                config.payment_scenario = payment_scenario
            if refund_scenario is not None:
                config.refund_scenario = refund_scenario
            if delay_seconds is not None:
                config.delay_seconds = delay_seconds
            config.version += 1
            config.updated_at = NOW


async def _simulate(database, scenario, delay_seconds):
    await _configure(database, payment_scenario=scenario, delay_seconds=delay_seconds)
    order_id = uuid4()
    result = await _send(
        database,
        _envelope(
            "ProcessPayment",
            {
                "orderId": str(order_id),
                "operationId": str(uuid4()),
                "customerId": str(uuid4()),
                "amount": "430000",
                "currency": "VND",
            },
        ),
    )
    assert result.disposition == "applied"
    return order_id


async def _payment(database, order_id):
    async with database.session() as session:
        payment = await session.scalar(
            select(PaymentAttempt).where(PaymentAttempt.order_id == order_id)
        )
        assert payment is not None
        return _loaded(payment)


async def _events(database, order_id):
    async with database.session() as session:
        rows = (
            await session.scalars(
                select(OutboxMessage.message_type).where(
                    OutboxMessage.payload["orderId"].as_string() == str(order_id)
                )
            )
        ).all()
    return list(rows)


def _loaded(payment):
    return type(
        "LoadedPayment",
        (),
        {
            "id": payment.id,
            "status": payment.status,
            "amount": payment.amount,
            "failure_code": payment.failure_code,
            "collected_by": payment.collected_by,
        },
    )()


def _database_command(*arguments, env):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/database.py"), *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result


_ = (UUID, func)
