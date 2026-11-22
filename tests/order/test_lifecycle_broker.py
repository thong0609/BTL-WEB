import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_lifecycle_api import api, post, state
from test_worker_database import create, response
from test_worker_rabbitmq import get_eventually, transport

from commerce_backend_common.messaging import parse_envelope
from commerce_backend_common.messaging_topology import EVENTS as EXCHANGE
from commerce_order.domain.enums import OrderStatus
from commerce_order.messaging.outbox import OutboxPublisher
from commerce_order.messaging.schemas import EVENTS
from commerce_order.models import OutboxMessage
from commerce_order.repositories.messaging import OutboxRepository

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "method,ending",
    [
        ("COD", "complete"),
        ("SIMULATED", "complete"),
        ("COD", "cancel"),
        ("SIMULATED", "cancel"),
        ("SIMULATED", "decline"),
    ],
)
def test_full_order_workflows_over_real_broker(
    order_runtime_store, rabbitmq_test, create_payload, quote_payload, method, ending
):
    async def exercise():
        store = order_runtime_store
        create_payload["paymentMethod"] = method
        initial = await create(store, create_payload, quote_payload)
        order_id, payment_id = initial.aggregate_id, uuid4()
        reservation_id = uuid4()
        async with (
            transport(store, rabbitmq_test) as (broker, consumer, settings),
            api(store) as client,
        ):
            publisher = OutboxPublisher(OutboxRepository(store["sessions"]), broker, settings)

            async def take(queue_name, expected):
                queue = await (await broker.ready_channel()).get_queue(queue_name)
                delivery = await get_eventually(queue)
                envelope = parse_envelope(delivery.body)
                assert envelope.message_type == expected
                async with store["sessions"]() as session:
                    source = await session.get(OutboxMessage, UUID(delivery.message_id))
                assert source.payload == envelope.payload
                await delivery.ack()
                return source

            async def reply(source, kind, **payload):
                event = response(source, kind, **payload)
                # Simulate producer redelivery; effects must still happen once.
                for _ in range(2):
                    await broker.publish(EXCHANGE, EVENTS[kind][0], event.envelope)
                assert await consumer.once() == 2

            assert await publisher.once() == 1
            reserve = await take("inventory.commands", "ReserveStock")
            await reply(
                reserve,
                "StockReserved",
                reservationId=str(reservation_id),
                items=reserve.payload["items"],
            )
            assert await publisher.once() == 1
            pay = await take(
                "payment.commands", "InitializeCodPayment" if method == "COD" else "ProcessPayment"
            )
            assert pay.payload["amount"] == "430000" and pay.payload["currency"] == "VND"
            if ending == "decline":
                await reply(
                    pay,
                    "PaymentFailed",
                    paymentId=str(payment_id),
                    paymentVersion=1,
                    paymentStatus="FAILED",
                    amount="430000",
                    currency="VND",
                    code="SIMULATED_DECLINE",
                )
                assert (await state(store, order_id))[0].status == OrderStatus.CANCELLING
                assert await publisher.once() == 1
                release = await take("inventory.commands", "ReleaseStock")
                await reply(release, "StockReleased", reservationId=str(reservation_id))
                assert (await state(store, order_id))[0].status == OrderStatus.CANCELLED
                return
            await reply(
                pay,
                "PaymentInitialized" if method == "COD" else "PaymentSucceeded",
                paymentId=str(payment_id),
                paymentVersion=1,
                paymentStatus="AWAITING_COLLECTION" if method == "COD" else "SUCCEEDED",
                method=method,
                amount="430000",
                currency="VND",
            )
            assert (await state(store, order_id))[0].status == OrderStatus.AWAITING_CONFIRMATION
            if ending == "cancel":
                cancelled = await post(
                    client,
                    order_id,
                    "cancel",
                    {"reason": "cancel fixture"},
                    actor="customer-a",
                    customer=True,
                )
                assert cancelled.status_code == 202
                assert await publisher.once() == 2
                release = await take("inventory.commands", "ReleaseStock")
                money = await take(
                    "payment.commands", "CancelCodPayment" if method == "COD" else "RefundPayment"
                )
                payload = {
                    "paymentId": str(payment_id),
                    "paymentVersion": 2,
                    "paymentStatus": "CANCELLED" if method == "COD" else "REFUNDED",
                    "amount": "430000",
                    "currency": "VND",
                }
                if method == "SIMULATED":
                    payload["refundId"] = str(uuid4())
                    assert money.payload["amount"] == "430000"
                await reply(
                    money,
                    "CodPaymentCancelled" if method == "COD" else "PaymentRefunded",
                    **payload,
                )
                assert (await state(store, order_id))[0].status == OrderStatus.CANCELLING
                await reply(release, "StockReleased", reservationId=str(reservation_id))
                assert (await state(store, order_id))[0].status == OrderStatus.CANCELLED
                return
            assert (await post(client, order_id, "confirm")).status_code == 200
            assert (await post(client, order_id, "dispatch")).status_code == 202
            assert (await state(store, order_id))[0].status == OrderStatus.PREPARING
            assert await publisher.once() == 1
            commit = await take("inventory.commands", "CommitStock")
            await reply(commit, "StockCommitted", reservationId=str(reservation_id))
            assert (await state(store, order_id))[0].status == OrderStatus.SHIPPING
            completed = await post(
                client, order_id, "complete", {"delivered": True, "codCollected": method == "COD"}
            )
            assert completed.status_code == 202
            if method == "COD":
                assert completed.json()["status"] == "SHIPPING" and await publisher.once() == 1
                collection = await take("payment.commands", "RecordCodCollection")
                await reply(
                    collection,
                    "CodCollected",
                    paymentId=str(payment_id),
                    paymentVersion=2,
                    paymentStatus="SUCCEEDED",
                    amount="430000",
                    currency="VND",
                    collectedBy=collection.payload["collectedBy"],
                )
            assert (await state(store, order_id))[0].status == OrderStatus.COMPLETED
            assert await publisher.once() == 0
            async with store["sessions"]() as session:
                rows = list(await session.scalars(select(OutboxMessage)))
                assert len(rows) == (4 if method == "COD" else 3)
                assert all(row.status == "PUBLISHED" for row in rows)

    asyncio.run(exercise())
