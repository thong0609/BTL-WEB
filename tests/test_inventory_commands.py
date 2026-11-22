"""INV-02 isolated transactions, concurrency, recovery and AMQP contract checks."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, select
from test_inventory_api import inventory_database, sql  # noqa: F401

from commerce_backend_common.database import Database
from commerce_backend_common.messaging import Broker, MessageEnvelope, PublishUnconfirmed
from commerce_backend_common.messaging_topology import declare_topology
from commerce_inventory.commands import InvalidCommand, parse_command, process_command
from commerce_inventory.db import SPEC
from commerce_inventory.main import create_app
from commerce_inventory.models import (
    InventoryOperation,
    OutboxMessage,
    ProcessedMessage,
    Reservation,
    StockItem,
    StockMovement,
)
from commerce_inventory.outbox import publish_one
from commerce_inventory.settings import Settings
from commerce_inventory.worker import consume
from commerce_inventory.worker import run as run_worker

FIXTURES = json.loads((Path(__file__).parent / "fixtures/inventory_messages.json").read_text())


@pytest.mark.parametrize("raw", FIXTURES["commands"], ids=lambda raw: raw["type"])
def test_shared_command_fixtures(raw):
    parse_command(MessageEnvelope.model_validate(raw))


def command(kind="ReserveStock", *, order_id=None, operation_id=None, **payload):
    return MessageEnvelope.new(
        kind,
        uuid4(),
        {
            "orderId": str(order_id or uuid4()),
            "operationId": str(operation_id or uuid4()),
            **payload,
        },
    )


def fresh_message(envelope):
    return envelope.model_copy(update={"message_id": uuid4()})


def reserve_command(product_id, quantity=1, **kwargs):
    return command(items=[{"productId": str(product_id), "quantity": quantity}], **kwargs)


@pytest.mark.parametrize("quantity", [0, -1, True, "1", 1.2, 2_147_483_648])
def test_command_quantity_is_strict(quantity):
    with pytest.raises(ValidationError):
        parse_command(reserve_command(uuid4(), quantity))


def test_contract_validation():
    line = {"productId": str(uuid4()), "quantity": 1}
    for items in ([], [line, line], [line] * 51):
        with pytest.raises(ValidationError):
            parse_command(command(items=items))
    with pytest.raises(InvalidCommand):
        parse_command(command("UnknownCommand"))
    with pytest.raises(InvalidCommand):
        parse_command(reserve_command(uuid4()), "inventory.release")
    for reason in ("", " "):
        with pytest.raises(ValidationError):
            parse_command(command("ReleaseStock", reservationId=str(uuid4()), reason=reason))
    probe = reserve_command(uuid4())
    probe.payload["futureOptionalField"] = "ignored"
    parse_command(probe)
    raw = probe.model_dump(mode="json")
    raw["version"] = 2
    with pytest.raises(ValidationError):
        MessageEnvelope.model_validate(raw)


@pytest.fixture
def inv02(inventory_database):  # noqa: F811
    sql(
        inventory_database,
        "TRUNCATE commerce_inventory.stock_items, "
        "commerce_inventory.reservations, "
        "commerce_inventory.inventory_operations, commerce_inventory.processed_messages, "
        "commerce_inventory.outbox_messages CASCADE",
    )
    settings = Settings(
        _env_file=None,
        database_enabled=True,
        database_url=inventory_database["runtime_url"],
        db_ssl_mode="disable",
        inventory_order_token="order-only",
        inventory_catalog_token="catalog-only",
    )
    return settings, inventory_database


async def seed(database, *quantities):
    ids = [uuid4() for _ in quantities]
    async with database.session() as session, session.begin():
        session.add_all(
            [
                StockItem(product_id=key, on_hand_quantity=quantity)
                for key, quantity in zip(ids, quantities, strict=True)
            ]
        )
    return ids


async def process(database, envelope):
    async with database.session() as session:
        return await process_command(session, envelope)


async def records(database, model):
    async with database.session() as session:
        return list((await session.scalars(select(model))).all())


async def take(queue):
    # basic.get returns immediately when empty; its timeout is not a wait-for-delivery.
    async with asyncio.timeout(5):
        while True:
            message = await queue.get(fail=False)
            if message is not None:
                return message
            await asyncio.sleep(0.05)


def exercise(settings, callback):
    async def run():
        database = Database(settings, SPEC)
        try:
            await callback(database)
        finally:
            await database.close()

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.parametrize(
    "kind,target", [("ReleaseStock", "RELEASED"), ("CommitStock", "COMMITTED")]
)
def test_transitions_duplicates_and_terminal_states(inv02, kind, target):
    async def run(database):
        (product,) = await seed(database, 10)
        request = reserve_command(product, 3)
        reserved = await process(database, request)
        assert reserved["type"] == "StockReserved"
        assert await process(database, request) is None
        assert await process(database, fresh_message(request)) == reserved
        # New operation for the same order must not reserve twice either.
        assert (
            await process(
                database, reserve_command(product, 3, order_id=request.payload["orderId"])
            )
            == reserved
        )
        finish = command(
            kind,
            order_id=request.payload["orderId"],
            reservationId=reserved["reservationId"],
            **({"reason": "Customer cancellation"} if kind == "ReleaseStock" else {}),
        )
        done = await process(database, finish)
        assert done["type"] == ("StockReleased" if target == "RELEASED" else "StockCommitted")
        assert await process(database, fresh_message(finish)) == done
        same_target = fresh_message(finish)
        same_target.payload = {**finish.payload, "operationId": str(uuid4())}
        assert await process(database, same_target) == done
        opposite = command(
            "CommitStock" if kind == "ReleaseStock" else "ReleaseStock",
            order_id=request.payload["orderId"],
            reservationId=reserved["reservationId"],
            **({"reason": "cancel"} if kind == "CommitStock" else {}),
        )
        assert (await process(database, opposite))["code"] == "RESERVATION_STATE_CONFLICT"
        assert (
            await process(
                database, reserve_command(product, 1, order_id=request.payload["orderId"])
            )
        )["code"] == "RESERVATION_STATE_CONFLICT"
        (stock,) = await records(database, StockItem)
        assert (stock.on_hand_quantity, stock.reserved_quantity, stock.version) == (
            10 if target == "RELEASED" else 7,
            0,
            2,
        )
        (reservation,) = await records(database, Reservation)
        assert reservation.status == target
        assert len(await records(database, StockMovement)) == 2

    exercise(inv02[0], run)


@pytest.mark.integration
def test_all_or_nothing_and_rejected_operation_replay(inv02):
    async def run(database):
        first, empty = await seed(database, 5, 0)
        request = command(
            items=[
                {"productId": str(first), "quantity": 2},
                {"productId": str(empty), "quantity": 1},
            ]
        )
        result = await process(database, request)
        assert result["code"] == "INSUFFICIENT_STOCK"
        assert result["shortages"] == [{"productId": str(empty), "requested": 1, "available": 0}]
        assert not await records(database, Reservation)
        assert not await records(database, StockMovement)
        async with database.session() as session, session.begin():
            stock = await session.get(StockItem, empty)
            stock.on_hand_quantity = 10
        assert await process(database, fresh_message(request)) == result
        assert all(row.reserved_quantity == 0 for row in await records(database, StockItem))
        assert (await process(database, reserve_command(uuid4())))["code"] == "PRODUCT_NOT_STOCKED"
        changed = fresh_message(request)
        changed.payload = {**request.payload, "items": [{"productId": str(first), "quantity": 1}]}
        assert (await process(database, changed))["code"] == "OPERATION_CONFLICT"
        # Reuse of a transport ID with altered content is a permanent poison message.
        with pytest.raises(InvalidCommand):
            await process(database, changed.model_copy(update={"message_id": request.message_id}))

    exercise(inv02[0], run)


@pytest.mark.integration
def test_twenty_buyers_last_item_and_duplicate_operation_race(inv02):
    async def run(database):
        product, other = await seed(database, 1, 5)
        results = await asyncio.gather(
            *[process(database, reserve_command(product)) for _ in range(20)]
        )
        assert sum(row["type"] == "StockReserved" for row in results) == 1
        request = reserve_command(other, 2)
        results = await asyncio.gather(
            *[process(database, fresh_message(request)) for _ in range(8)]
        )
        assert all(row == results[0] for row in results)
        assert len(await records(database, StockMovement)) == 2
        assert len(await records(database, Reservation)) == 2
        assert all(row.available_quantity >= 0 for row in await records(database, StockItem))

    exercise(inv02[0], run)


@pytest.mark.integration
def test_cancel_dispatch_race_and_order_ownership(inv02):
    async def run(database):
        (product,) = await seed(database, 10)
        request = reserve_command(product, 3)
        result = await process(database, request)
        reservation_id = result["reservationId"]
        wrong_order = command("CommitStock", reservationId=reservation_id)
        assert (await process(database, wrong_order))["code"] == "RESERVATION_NOT_FOUND"
        results = await asyncio.gather(
            process(
                database,
                command(
                    "CommitStock", order_id=request.payload["orderId"], reservationId=reservation_id
                ),
            ),
            process(
                database,
                command(
                    "ReleaseStock",
                    order_id=request.payload["orderId"],
                    reservationId=reservation_id,
                    reason="cancel",
                ),
            ),
        )
        assert sum("code" not in row for row in results) == 1
        assert len(await records(database, StockMovement)) == 2
        (stock,) = await records(database, StockItem)
        assert stock.reserved_quantity == 0 and stock.on_hand_quantity in (7, 10)

    exercise(inv02[0], run)


@pytest.mark.integration
def test_outbox_failure_rolls_back_entire_command(inv02):
    async def run(database):
        (product,) = await seed(database, 10)
        request = reserve_command(product, 2)

        def fail(*args):
            raise RuntimeError("injected outbox failure")

        event.listen(OutboxMessage, "before_insert", fail)
        try:
            with pytest.raises(RuntimeError):
                await process(database, request)
        finally:
            event.remove(OutboxMessage, "before_insert", fail)
        for model in (
            InventoryOperation,
            Reservation,
            StockMovement,
            ProcessedMessage,
            OutboxMessage,
        ):
            assert not await records(database, model)
        (stock,) = await records(database, StockItem)
        assert stock.reserved_quantity == 0 and stock.version == 0
        assert (await process(database, request))["type"] == "StockReserved"

    exercise(inv02[0], run)


@pytest.mark.integration
def test_outbox_unknown_publish_outcome_retries_same_id(inv02):
    async def run(database):
        (product,) = await seed(database, 10)
        await process(database, reserve_command(product))

        class Publisher:
            seen = []
            failing = True

            async def publish(self, exchange, routing_key, envelope):
                self.seen.append(envelope)
                if self.failing:
                    raise PublishUnconfirmed("sensitive-error-credential")

        publisher = Publisher()
        assert await publish_one(database, publisher)
        (row,) = await records(database, OutboxMessage)
        assert row.status == "PENDING" and row.attempt_count == 1
        assert "sensitive" not in row.last_error
        assert not await publish_one(database, publisher)
        async with database.session() as session, session.begin():
            row = await session.get(OutboxMessage, row.id)
            row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        publisher.failing = False
        assert await publish_one(database, publisher)
        assert publisher.seen[0] == publisher.seen[1]
        (row,) = await records(database, OutboxMessage)
        assert row.status == "PUBLISHED" and row.attempt_count == 2
        assert row.last_error is None

    exercise(inv02[0], run)


def test_internal_routes_authenticate_before_database():
    settings = Settings(
        _env_file=None, inventory_order_token="order-only", inventory_catalog_token="catalog-only"
    )
    app = create_app(settings)
    with TestClient(app) as client:
        for token in (None, "customer-token", "wrong"):
            response = client.post(
                "/internal/availability/batch",
                json={"productIds": [str(uuid4())]},
                headers={"Authorization": f"Bearer {token}"} if token else {},
            )
            assert response.status_code == 401
        path = f"/internal/reservations/by-order/{uuid4()}"
        assert client.get(path, headers={"Authorization": "Bearer catalog-only"}).status_code == 403
        assert client.get(path, headers={"Authorization": "Bearer order-only"}).status_code == 503
    with pytest.raises(ValidationError):
        Settings(_env_file=None, inventory_order_token="same", inventory_catalog_token="same")
    # Caller permissions belong to the route, independent of deployment prefixes.
    mounted = FastAPI()
    mounted.mount("/inventory", app)
    with TestClient(mounted) as client:
        assert (
            client.get(
                f"/inventory/internal/reservations/by-order/{uuid4()}",
                headers={"Authorization": "Bearer catalog-only"},
            ).status_code
            == 403
        )


@pytest.mark.integration
def test_identical_message_concurrency_and_multi_product_lock_order(inv02):
    async def run(database):
        first, second = await seed(database, 5, 5)
        request = command(
            items=[
                {"productId": str(first), "quantity": 2},
                {"productId": str(second), "quantity": 2},
            ]
        )
        results = await asyncio.gather(*[process(database, request) for _ in range(8)])
        assert sum(result is not None for result in results) == 1
        assert len(await records(database, OutboxMessage)) == 1
        reversed_order = command(items=list(reversed(request.payload["items"])))
        another = command(items=request.payload["items"])
        results = await asyncio.gather(
            process(database, reversed_order), process(database, another)
        )
        assert sum(result["type"] == "StockReserved" for result in results) == 1
        assert all(stock.reserved_quantity == 4 for stock in await records(database, StockItem))

    exercise(inv02[0], run)


@pytest.mark.integration
def test_release_rollback_restores_reservation_counters_and_history(inv02):
    async def run(database):
        (product,) = await seed(database, 10)
        request = reserve_command(product, 3)
        result = await process(database, request)
        release = command(
            "ReleaseStock",
            order_id=request.payload["orderId"],
            reservationId=result["reservationId"],
            reason="cancel",
        )

        def fail(*args):
            raise RuntimeError("injected movement failure")

        event.listen(StockMovement, "before_insert", fail)
        try:
            with pytest.raises(RuntimeError):
                await process(database, release)
        finally:
            event.remove(StockMovement, "before_insert", fail)
        (reservation,) = await records(database, Reservation)
        (stock,) = await records(database, StockItem)
        assert reservation.status == "RESERVED" and reservation.released_at is None
        assert stock.reserved_quantity == 3
        assert len(await records(database, InventoryOperation)) == 1
        assert len(await records(database, ProcessedMessage)) == 1
        assert len(await records(database, OutboxMessage)) == 1
        assert (await process(database, release))["type"] == "StockReleased"

    exercise(inv02[0], run)


@pytest.mark.integration
def test_outbox_concurrent_workers_and_recovery_after_cancel(inv02):
    async def run(database):
        (product,) = await seed(database, 10)
        await process(database, reserve_command(product))
        entered = asyncio.Event()
        blocked = asyncio.Event()

        class Publisher:
            events = []

            async def publish(self, exchange, route, envelope):
                self.events.append(envelope)
                entered.set()
                await blocked.wait()

        publisher = Publisher()
        first = asyncio.create_task(publish_one(database, publisher))
        await asyncio.wait_for(entered.wait(), timeout=5)
        # Another worker skips the lease; a crash/cancellation is reclaimed after expiry.
        assert not await publish_one(database, publisher)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        (row,) = await records(database, OutboxMessage)
        assert row.status == "PROCESSING" and row.attempt_count == 1
        async with database.session() as session, session.begin():
            row = await session.get(OutboxMessage, row.id)
            row.locked_until = datetime.now(UTC) - timedelta(seconds=1)
        blocked.set()
        assert await publish_one(database, publisher)
        assert publisher.events[0] == publisher.events[1]

    exercise(inv02[0], run)


@pytest.mark.integration
@pytest.mark.parametrize("expected", FIXTURES["events"], ids=lambda raw: raw["type"])
def test_producer_matches_shared_event_fixtures(inv02, monkeypatch, expected):
    async def run(database):
        reserve, release, commit = [
            MessageEnvelope.model_validate(raw) for raw in FIXTURES["commands"]
        ]
        kind = expected["type"]
        async with database.session() as session, session.begin():
            session.add(
                StockItem(
                    product_id=UUID(reserve.payload["items"][0]["productId"]),
                    on_hand_quantity=1 if kind == "StockReservationFailed" else 10,
                )
            )
        monkeypatch.setattr(
            "commerce_inventory.commands.uuid4", lambda: UUID(release.payload["reservationId"])
        )
        await process(database, reserve)
        if kind == "StockReleaseFailed":
            await process(database, commit)
        if kind == "StockCommitFailed":
            await process(database, release)
        if kind in ("StockReleased", "StockReleaseFailed"):
            await process(database, release)
        if kind in ("StockCommitted", "StockCommitFailed"):
            await process(database, commit)
        (result,) = [
            row for row in await records(database, OutboxMessage) if row.message_type == kind
        ]
        fixture = MessageEnvelope.model_validate(expected)
        assert result.payload == fixture.payload
        assert result.correlation_id == fixture.correlation_id
        assert result.causation_id == fixture.causation_id

    exercise(inv02[0], run)


@pytest.mark.integration
def test_outbox_stale_publisher_cannot_overwrite_new_claim(inv02):
    async def run(database):
        (product,) = await seed(database, 10)
        await process(database, reserve_command(product))

        class Publisher:
            async def publish(self, exchange, route, envelope):
                # Model an old sender resuming after another worker reclaimed its lease.
                async with database.session() as session, session.begin():
                    row = await session.get(OutboxMessage, envelope.message_id)
                    row.locked_by = "new-worker"

        assert await publish_one(database, Publisher())
        (row,) = await records(database, OutboxMessage)
        assert row.status == "PROCESSING" and row.locked_by == "new-worker"

    exercise(inv02[0], run)


@pytest.mark.integration
def test_internal_snapshot_and_missing_products(inv02):
    state = {}

    async def run(database):
        (product,) = await seed(database, 10)
        request = reserve_command(product, 3)
        result = await process(database, request)
        state.update(product=str(product), order=request.payload["orderId"], result=result)

    exercise(inv02[0], run)
    with TestClient(create_app(inv02[0])) as client:
        unknown = str(uuid4())
        headers = {"Authorization": "Bearer catalog-only"}
        result = client.post(
            "/internal/availability/batch",
            headers=headers,
            json={"productIds": [state["product"], unknown]},
        )
        assert result.status_code == 200
        assert result.json()["items"] == [
            {"productId": state["product"], "stocked": True, "availableQuantity": 7},
            {"productId": unknown, "stocked": False, "availableQuantity": 0},
        ]
        headers = {"Authorization": "Bearer order-only"}
        result = client.get(f"/internal/reservations/by-order/{state['order']}", headers=headers)
        assert result.status_code == 200
        assert result.json()["reservationId"] == state["result"]["reservationId"]
        assert result.json()["status"] == "RESERVED"
        assert (
            client.get(f"/internal/reservations/by-order/{uuid4()}", headers=headers).status_code
            == 404
        )
        assert (
            client.post(
                "/internal/availability/batch", headers=headers, json={"productIds": []}
            ).status_code
            == 400
        )


@pytest.mark.integration
def test_real_broker_delivery_redelivery_outbox_and_dlq(inv02, rabbitmq_test):
    async def run(database):
        settings = inv02[0].model_copy(
            update={
                "broker_enabled": True,
                "broker_url": Settings(_env_file=None, broker_url=rabbitmq_test["url"]).broker_url,
            }
        )
        broker = Broker(settings)
        try:
            channel = await broker.ready_channel()
            await declare_topology(channel, "inventory-service")
            await declare_topology(channel, "order-service")
            queue = await channel.get_queue("inventory.commands")
            events = await channel.get_queue("order.events")
            dead = await channel.get_queue("inventory.commands.dead")
            for current in (queue, events, dead):
                await current.purge()
            (product,) = await seed(database, 10)
            request = reserve_command(product, 2)
            await broker.publish("commerce.commands", "inventory.reserve", request)
            message = await take(queue)
            # Simulate DB commit followed by process loss before ACK.
            await process(database, request)
            await message.nack(requeue=True)
            await run_worker(settings, once=True)
            assert len(await records(database, StockMovement)) == 1
            assert len(await records(database, OutboxMessage)) == 1
            delivered = await take(events)
            payload = MessageEnvelope.model_validate_json(delivered.body)
            assert payload.message_type == "StockReserved"
            assert payload.causation_id == request.message_id
            assert payload.payload["operationId"] == request.payload["operationId"]
            await delivered.ack()
            invalid = command("UnknownCommand")
            await broker.publish("commerce.commands", "inventory.reserve", invalid)
            await consume(await take(queue), database, settings.broker_max_message_bytes)
            rejected = await take(dead)
            assert rejected.message_id == str(invalid.message_id)
            assert rejected.headers["x-death"]
            await rejected.ack()
        finally:
            await broker.close()

    exercise(inv02[0], run)
