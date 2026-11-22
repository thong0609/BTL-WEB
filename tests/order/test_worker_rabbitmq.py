import asyncio
import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import timedelta

import aio_pika
import pytest
from sqlalchemy import func, select, update
from test_worker_database import create, response

from commerce_backend_common.messaging import Broker, PublishUnconfirmed, parse_envelope
from commerce_backend_common.messaging_topology import EVENTS, SERVICE_QUEUE, declare_topology
from commerce_order.messaging.consumer import ORIGINAL_ROUTE, RETRY_COUNT, EventConsumer
from commerce_order.messaging.handlers import EventHandlers
from commerce_order.messaging.inbox import InboxProcessor
from commerce_order.messaging.outbox import OutboxPublisher
from commerce_order.models import OrderWorkflow, OutboxMessage, ProcessedMessage
from commerce_order.models.messaging import OutboxStatus
from commerce_order.repositories.messaging import OutboxRepository
from commerce_order.settings import Settings

pytestmark = pytest.mark.integration


async def get_eventually(queue):
    async with asyncio.timeout(8):
        while True:
            message = await queue.get(no_ack=False, fail=False, timeout=5)
            if message is not None:
                return message
            await asyncio.sleep(0.03)


@asynccontextmanager
async def transport(store, rabbit, handlers=None):
    settings = Settings(
        app_env="test",
        broker_enabled=True,
        broker_url=rabbit["url"],
        order_event_retry_delays_ms=[50, 100],
        order_event_max_attempts=3,
    )
    broker = Broker(settings, role="order-step9-test")
    try:
        await broker.open()
        channel = await broker.ready_channel()
        for service in SERVICE_QUEUE:
            await declare_topology(channel, service)
        consumer = EventConsumer(broker, InboxProcessor(store["sessions"], handlers), settings)
        await consumer.prepare()
        for name in [
            *SERVICE_QUEUE.values(),
            "order.events.dead",
            "order.events.retry.50",
            "order.events.retry.100",
        ]:
            await (await channel.get_queue(name)).purge()
        yield broker, consumer, settings
    finally:
        await broker.close()


async def reserved(store, payload, quote):
    from uuid import uuid4

    command = await create(store, payload, quote)
    event = response(
        command, "StockReserved", reservationId=str(uuid4()), items=command.payload["items"]
    )
    return command, event


def test_broker_publish_crash_and_lease_takeover_keep_exact_message(
    order_runtime_store, rabbitmq_test, create_payload, quote_payload, monkeypatch
):
    async def exercise():
        command = await create(order_runtime_store, create_payload, quote_payload)
        async with transport(order_runtime_store, rabbitmq_test) as (broker, _, settings):
            repository = OutboxRepository(order_runtime_store["sessions"])
            publisher = OutboxPublisher(repository, broker, settings)
            original = repository.published

            async def crash_after_confirm(claim):
                raise RuntimeError("process stopped after broker confirm")

            monkeypatch.setattr(repository, "published", crash_after_confirm)
            with pytest.raises(RuntimeError):
                await publisher.once()
            queue = await (await broker.ready_channel()).get_queue("inventory.commands")
            first = await get_eventually(queue)
            assert first.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
            first_body = first.body
            await first.ack()
            async with order_runtime_store["sessions"]() as session, session.begin():
                row = await session.get(OutboxMessage, command.id)
                assert row.status == OutboxStatus.PROCESSING and row.published_at is None
                await session.execute(
                    update(OutboxMessage)
                    .where(OutboxMessage.id == command.id)
                    .values(locked_until=func.clock_timestamp() - timedelta(seconds=1))
                )
            monkeypatch.setattr(repository, "published", original)
            assert await publisher.once() == 1
            second = await get_eventually(queue)
            assert second.body == first_body and second.message_id == str(command.id)
            assert parse_envelope(second.body).occurred_at == command.created_at
            await second.ack()

    asyncio.run(exercise())


def test_live_subscription_commits_before_ack_and_duplicate_has_no_second_effect(
    order_runtime_store, rabbitmq_test, create_payload, quote_payload, monkeypatch
):
    async def exercise():
        command, event = await reserved(order_runtime_store, create_payload, quote_payload)
        async with transport(order_runtime_store, rabbitmq_test) as (broker, consumer, _):
            acknowledged = asyncio.Event()
            ack_count = 0
            original_ack = aio_pika.IncomingMessage.ack

            async def verify_commit(message, multiple=False):
                nonlocal ack_count
                if message.message_id == str(event.envelope.message_id):
                    async with order_runtime_store["sessions"]() as session:
                        assert (
                            await session.scalar(select(func.count()).select_from(ProcessedMessage))
                            == 1
                        )
                        assert (
                            await session.scalar(select(func.count()).select_from(OutboxMessage))
                            == 2
                        )
                    ack_count += 1
                await original_ack(message, multiple=multiple)
                acknowledged.set()

            monkeypatch.setattr(aio_pika.IncomingMessage, "ack", verify_commit)
            runner = asyncio.create_task(consumer.run())
            try:
                async with asyncio.timeout(8):
                    while not consumer.started.is_set():
                        if runner.done():
                            await runner
                        await asyncio.sleep(0.03)
                for _ in range(2):
                    acknowledged.clear()
                    await broker.publish(EVENTS, "inventory.stock-reserved", event.envelope)
                    await asyncio.wait_for(acknowledged.wait(), timeout=8)
                assert ack_count == 2
                async with order_runtime_store["sessions"]() as session:
                    flow = await session.get(OrderWorkflow, command.aggregate_id)
                    assert flow.version == 1 and flow.stock_step == "RESERVED"
            finally:
                runner.cancel()
                await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(exercise())


def test_commit_then_channel_crash_redelivers_and_inbox_replays(
    order_runtime_store, rabbitmq_test, create_payload, quote_payload
):
    async def exercise():
        _, event = await reserved(order_runtime_store, create_payload, quote_payload)
        async with transport(order_runtime_store, rabbitmq_test) as (broker, consumer, _):
            await broker.publish(EVENTS, "inventory.stock-reserved", event.envelope)
            auxiliary = await broker.connection.channel()
            delivered = await get_eventually(await auxiliary.get_queue("order.events"))
            assert await consumer.processor.process(event) == "applied"
            await auxiliary.close()  # Crash after commit, before ACK.
            replay = await get_eventually(consumer.queue)
            assert replay.redelivered and replay.message_id == delivered.message_id
            await consumer.handle(replay)
            async with order_runtime_store["sessions"]() as session:
                assert await session.scalar(select(func.count()).select_from(ProcessedMessage)) == 1
                assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 2

    asyncio.run(exercise())


def test_db_fault_rolls_back_then_durable_retry_succeeds(
    order_runtime_store, rabbitmq_test, create_payload, quote_payload
):
    async def exercise():
        _, event = await reserved(order_runtime_store, create_payload, quote_payload)

        class OnceFault(EventHandlers):
            calls = 0

            async def apply(self, session, locked, event):
                changed = await super().apply(session, locked, event)
                self.calls += 1
                if self.calls == 1:
                    await session.flush()
                    raise RuntimeError("private database fault")
                return changed

        async with transport(order_runtime_store, rabbitmq_test, OnceFault()) as (
            broker,
            consumer,
            _,
        ):
            await broker.publish(EVENTS, "inventory.stock-reserved", event.envelope)
            message = await get_eventually(consumer.queue)
            original = message.body
            await consumer.handle(message)
            async with order_runtime_store["sessions"]() as session:
                assert await session.scalar(select(func.count()).select_from(ProcessedMessage)) == 0
                assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 1
            retry = await get_eventually(consumer.queue)
            assert retry.body == original and retry.message_id == message.message_id
            assert (
                retry.headers[RETRY_COUNT] == 1
                and retry.headers[ORIGINAL_ROUTE] == "inventory.stock-reserved"
            )
            assert retry.exchange == "" and retry.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
            await consumer.handle(retry)
            async with order_runtime_store["sessions"]() as session:
                assert await session.scalar(select(func.count()).select_from(ProcessedMessage)) == 1
                assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 2

    asyncio.run(exercise())


def test_exhausted_db_failures_go_to_dead_queue_without_inbox(
    order_runtime_store, rabbitmq_test, create_payload, quote_payload
):
    async def exercise():
        _, event = await reserved(order_runtime_store, create_payload, quote_payload)

        class AlwaysFault(EventHandlers):
            async def apply(self, session, locked, event):
                await super().apply(session, locked, event)
                await session.flush()
                raise RuntimeError("private persistent fault")

        async with transport(order_runtime_store, rabbitmq_test, AlwaysFault()) as (
            broker,
            consumer,
            _,
        ):
            consumer.settings.order_event_retry_delays_ms = [50]
            consumer.settings.order_event_max_attempts = 4
            await broker.publish(EVENTS, "inventory.stock-reserved", event.envelope)
            for attempt in range(4):
                message = await get_eventually(consumer.queue)
                assert message.headers.get(RETRY_COUNT, 0) == attempt
                await consumer.handle(message)
            dead = await (await broker.ready_channel()).get_queue("order.events.dead")
            message = await get_eventually(dead)
            assert message.message_id == str(event.envelope.message_id)
            assert message.headers["x-order-dead-reason"] == "EVENT_RETRY_EXHAUSTED"
            await message.ack()
            assert await consumer.queue.get(no_ack=False, fail=False) is None
            async with order_runtime_store["sessions"]() as session:
                assert await session.scalar(select(func.count()).select_from(ProcessedMessage)) == 0
                assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 1

    asyncio.run(exercise())


def test_unknown_schema_version_is_deadlettered_without_processing(
    order_runtime_store, rabbitmq_test, create_payload, quote_payload
):
    async def exercise():
        _, event = await reserved(order_runtime_store, create_payload, quote_payload)
        async with transport(order_runtime_store, rabbitmq_test) as (broker, consumer, _):
            value = event.envelope.model_dump(mode="json")
            value["version"] = 2
            exchange = await (await broker.ready_channel()).get_exchange(EVENTS)
            await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(value).encode(), delivery_mode=aio_pika.DeliveryMode.PERSISTENT
                ),
                routing_key="inventory.stock-reserved",
                mandatory=True,
            )
            assert await consumer.once() == 1
            dead = await get_eventually(
                await (await broker.ready_channel()).get_queue("order.events.dead")
            )
            assert json.loads(dead.body)["version"] == 2
            await dead.ack()
            async with order_runtime_store["sessions"]() as session:
                assert await session.scalar(select(func.count()).select_from(ProcessedMessage)) == 0

    asyncio.run(exercise())


@pytest.mark.parametrize("destination", ["retry", "dead_letter"])
def test_retry_publish_failure_leaves_original_unacked(
    order_runtime_store, rabbitmq_test, create_payload, quote_payload, monkeypatch, destination
):
    async def exercise():
        _, event = await reserved(order_runtime_store, create_payload, quote_payload)

        class Fault(EventHandlers):
            async def apply(self, session, locked, event):
                raise RuntimeError("DB unavailable")

        async with transport(order_runtime_store, rabbitmq_test, Fault()) as (broker, consumer, _):
            envelope = event.envelope
            if destination == "dead_letter":
                envelope = envelope.model_copy(
                    update={"payload": {**envelope.payload, "items": []}}
                )
            await broker.publish(EVENTS, "inventory.stock-reserved", envelope)
            auxiliary = await broker.connection.channel()
            delivered = await get_eventually(await auxiliary.get_queue("order.events"))

            async def unconfirmed(*args):
                raise PublishUnconfirmed("retry unknown")

            monkeypatch.setattr(consumer, destination, unconfirmed)
            with pytest.raises(PublishUnconfirmed):
                await consumer.handle(delivered)
            assert not delivered.processed
            await auxiliary.close()
            redelivery = await get_eventually(consumer.queue)
            assert redelivery.redelivered and redelivery.message_id == delivered.message_id
            await redelivery.ack()

    asyncio.run(exercise())


def test_worker_all_once_runs_a_real_bounded_batch_without_leaking_secrets(
    order_runtime_store, rabbitmq_test, create_payload, quote_payload
):
    async def exercise():
        command = await create(order_runtime_store, create_payload, quote_payload)
        async with transport(order_runtime_store, rabbitmq_test) as (broker, _, _):
            env = {
                **os.environ,
                "APP_ENV": "test",
                "DATABASE_ENABLED": "true",
                "DATABASE_URL": order_runtime_store["url"],
                "DB_SSL_MODE": "disable",
                "BROKER_ENABLED": "true",
                "BROKER_URL": rabbitmq_test["url"],
                "ORDER_EVENT_RETRY_DELAYS_MS": "[50,100]",
            }
            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "commerce_order.worker", "--run", "--mode", "all", "--once"],
                env=env,
                capture_output=True,
                text=True,
                timeout=25,
            )
            assert result.returncode == 0, result.stdout
            assert '"published": 1' in result.stdout and '"received": 0' in result.stdout
            assert rabbitmq_test["password"] not in result.stdout + result.stderr
            message = await get_eventually(
                await (await broker.ready_channel()).get_queue("inventory.commands")
            )
            assert message.message_id == str(command.id)
            await message.ack()

    asyncio.run(exercise())
