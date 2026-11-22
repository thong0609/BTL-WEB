"""Explicit monitor/outbox/consumer worker. API startup never runs these loops."""

import argparse
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog

from commerce_backend_common.database import Database
from commerce_backend_common.logging import configure_logging
from commerce_backend_common.messaging import Broker, BrokerConfigurationError
from commerce_backend_common.messaging_topology import declare_topology
from commerce_backend_common.messaging_worker import monitor
from commerce_order.clients.recovery import InventorySnapshot, PaymentSnapshot, SnapshotClient
from commerce_order.db import SPEC
from commerce_order.messaging.consumer import EventConsumer
from commerce_order.messaging.inbox import InboxProcessor
from commerce_order.messaging.outbox import OutboxPublisher
from commerce_order.repositories.messaging import OutboxRepository
from commerce_order.services.recovery import RecoveryJob
from commerce_order.settings import Settings


@asynccontextmanager
async def recovery_job(settings: Settings, database: Database) -> AsyncIterator[RecoveryJob]:
    async with (
        httpx.AsyncClient(
            base_url=str(settings.inventory_base_url),
            timeout=settings.http_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=settings.http_max_connections),
        ) as inventory_http,
        httpx.AsyncClient(
            base_url=str(settings.payment_base_url),
            timeout=settings.http_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=settings.http_max_connections),
        ) as payment_http,
    ):
        yield RecoveryJob(
            database.session_factory,
            SnapshotClient(
                inventory_http,
                settings.inventory_service_token,
                InventorySnapshot,
                "/internal/reservations/by-order/",
            ),
            SnapshotClient(
                payment_http,
                settings.payment_service_token,
                PaymentSnapshot,
                "/internal/payments/by-order/",
            ),
            settings,
        )


async def run(settings: Settings, mode: str, *, once: bool) -> None:
    if mode == "monitor":
        await monitor(settings, once=once)
        return
    if not settings.database_enabled or (mode != "recovery" and not settings.broker_enabled):
        raise BrokerConfigurationError("Explicitly enable database and broker for business workers")
    configure_logging()
    database = Database(settings, SPEC)
    broker = None
    try:
        if await database.readiness() != "ready":
            raise BrokerConfigurationError("Order database is not ready")
        if mode == "recovery":
            async with recovery_job(settings, database) as recovery:
                if once:
                    count = await recovery.once()
                    structlog.get_logger().info("order_recovery_batch", count=count)
                else:
                    await recovery.run()
            return
        broker = Broker(settings, role=f"order-{mode}")
        await broker.open()
        await declare_topology(await broker.ready_channel(), "order-service")
        outbox = OutboxPublisher(OutboxRepository(database.session_factory), broker, settings)
        consumer = EventConsumer(broker, InboxProcessor(database.session_factory), settings)
        if once:
            published = await outbox.once() if mode in {"outbox", "all"} else 0
            received = await consumer.once() if mode in {"consumer", "all"} else 0
            if mode == "all" and settings.order_recovery_enabled:
                async with recovery_job(settings, database) as recovery:
                    await recovery.once()
            structlog.get_logger().info(
                "order_worker_batch", mode=mode, published=published, received=received
            )
        else:
            async with recovery_job(settings, database) as recovery, asyncio.TaskGroup() as tasks:
                if mode in {"outbox", "all"}:
                    tasks.create_task(outbox.run())
                if mode in {"consumer", "all"}:
                    tasks.create_task(consumer.run())
                if mode == "all" and settings.order_recovery_enabled:
                    tasks.create_task(recovery.run())
    finally:
        if broker is not None:
            await broker.close()
        await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument(
        "--mode", choices=["monitor", "outbox", "consumer", "all", "recovery"], default="monitor"
    )
    parser.add_argument(
        "--once", action="store_true", help="One bounded batch; monitor checks once"
    )
    args = parser.parse_args()
    if not args.run:
        parser.print_help()
        return 0
    try:
        asyncio.run(run(Settings(), args.mode, once=args.once))
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"Order worker stopped ({type(exc).__name__}); check database/broker configuration")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
