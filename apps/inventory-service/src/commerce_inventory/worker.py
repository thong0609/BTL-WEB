"""Explicit INV-02 consumer and outbox worker; the API never starts this worker."""

import argparse
import asyncio

import structlog
from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError

from commerce_backend_common.database import Database
from commerce_backend_common.logging import configure_logging
from commerce_backend_common.messaging import Broker, BrokerError, parse_envelope
from commerce_backend_common.messaging_topology import declare_topology
from commerce_inventory.commands import InvalidCommand, process_command
from commerce_inventory.db import SPEC
from commerce_inventory.outbox import publish_one
from commerce_inventory.settings import Settings

log = structlog.get_logger()


async def consume(message: AbstractIncomingMessage, database: Database, max_bytes: int) -> None:
    try:
        envelope = parse_envelope(message.body, max_bytes)
        async with database.session() as session:
            await process_command(session, envelope, message.routing_key)
    except (ValidationError, InvalidCommand, BrokerError):
        log.warning("inventory_command_rejected", reason="invalid_contract_or_message_identity")
        await message.reject(requeue=False)
    except Exception:
        log.warning("inventory_command_retry", reason="transaction_unavailable")
        await asyncio.sleep(1)
        await message.nack(requeue=True)
    else:
        # ACK only after commit; failed ACK is redelivered and deduplicated.
        await message.ack()


async def run(settings: Settings, *, once: bool = False) -> None:
    if not settings.database_enabled or not settings.broker_enabled:
        raise ValueError("Enable DATABASE_ENABLED and BROKER_ENABLED for the Inventory worker")
    database = Database(settings, SPEC)
    broker = Broker(settings, role="inventory-worker")
    try:
        channel = await broker.ready_channel()
        queue = await channel.get_queue("inventory.commands", ensure=True)
        if once:
            message = await queue.get(fail=False, timeout=5)
            if message is not None:
                await consume(message, database, settings.broker_max_message_bytes)
            await publish_one(database, broker)
            return

        active: set[asyncio.Task[None]] = set()

        async def handle(message: AbstractIncomingMessage) -> None:
            task = asyncio.current_task()
            assert task is not None
            active.add(task)
            try:
                await consume(message, database, settings.broker_max_message_bytes)
            finally:
                active.discard(task)

        tag = await queue.consume(handle)
        log.info("inventory_worker_started", queue="inventory.commands")
        try:
            while True:
                try:
                    sent = await publish_one(database, broker)
                except Exception:
                    log.warning("inventory_outbox_retry", reason="database_unavailable")
                    sent = False
                if not sent:
                    await asyncio.sleep(1)
        finally:
            try:
                await queue.cancel(tag)
            finally:
                pending = list(active)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
    finally:
        await broker.close()
        await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Consume commands and publish outbox")
    parser.add_argument("--once", action="store_true", help="Process at most one command/event")
    parser.add_argument("--declare-topology", action="store_true", help="Provision Inventory queue")
    args = parser.parse_args()
    if not args.run and not args.declare_topology:
        parser.print_help()
        return 0

    async def start() -> None:
        settings = Settings()
        if args.declare_topology:
            if not settings.broker_enabled:
                raise ValueError("Enable BROKER_ENABLED to provision topology")
            broker = Broker(settings, role="inventory-topology")
            try:
                await declare_topology(await broker.ready_channel(), settings.service_name)
            finally:
                await broker.close()
        if args.run:
            await run(settings, once=args.once)

    configure_logging()
    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"Inventory worker stopped ({type(exc).__name__}); verify DB/broker configuration")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
