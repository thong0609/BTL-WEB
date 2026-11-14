"""Consume payment.commands, publish outbox events, and settle delayed demo results."""

import argparse
import asyncio
from datetime import UTC, datetime

import structlog
from aio_pika.abc import AbstractIncomingMessage
from structlog.typing import FilteringBoundLogger

from commerce_backend_common.database import Database, DatabaseConfigurationError
from commerce_backend_common.logging import configure_logging
from commerce_backend_common.messaging import (
    Broker,
    BrokerConfigurationError,
    BrokerError,
    parse_envelope,
)
from commerce_backend_common.messaging_topology import declare_topology
from commerce_backend_common.messaging_worker import monitor
from commerce_payment.contracts import PaymentMessageError
from commerce_payment.db import SPEC
from commerce_payment.handling import COMMAND_CONSUMER, handle_message, settle_due
from commerce_payment.outbox import publish_pending
from commerce_payment.settings import Settings

_DLQ_ERRORS = {"INVALID_MESSAGE", "PAYLOAD_MISMATCH"}


async def _dispatch(
    database: Database,
    body: bytes,
    *,
    max_bytes: int,
    now: datetime,
) -> None:
    envelope = parse_envelope(body, max_bytes=max_bytes)
    async with database.session() as session:
        await handle_message(session, envelope, now=now)


async def _on_message(
    database: Database,
    settings: Settings,
    message: AbstractIncomingMessage,
) -> None:
    now = datetime.now(UTC)
    try:
        await _dispatch(
            database, message.body, max_bytes=settings.broker_max_message_bytes, now=now
        )
    except PaymentMessageError as failure:
        await message.reject(requeue=failure.code not in _DLQ_ERRORS)
        return
    except BrokerError:
        await message.reject(requeue=False)
        return
    except Exception:
        await message.reject(requeue=True)
        return
    await message.ack()


async def _background(
    database: Database, broker: Broker, log: FilteringBoundLogger
) -> None:
    while True:
        try:
            async with database.session() as session:
                settled = await settle_due(session, now=datetime.now(UTC))
                published = await publish_pending(session, broker)
            if settled or published:
                log.info("worker_tick", settled=settled, published=published)
        except Exception as exc:
            log.warning("worker_tick_failed", error=type(exc).__name__)
        await asyncio.sleep(2)


async def run_business(settings: Settings) -> None:
    if not settings.broker_enabled:
        raise BrokerConfigurationError("Enable BROKER_ENABLED before running the business worker")
    if not settings.database_enabled or not settings.database_url:
        raise DatabaseConfigurationError("Enable DATABASE_ENABLED with DATABASE_URL")
    configure_logging()
    log = structlog.get_logger().bind(service=settings.service_name, mode="business", consumers=1)
    database = Database(settings, SPEC)
    broker = Broker(settings, role="worker")
    tick: asyncio.Task[None] | None = None
    try:
        await broker.open()
        channel = await broker.ready_channel()
        await declare_topology(channel, settings.service_name)
        queue = await channel.get_queue(COMMAND_CONSUMER)
        tick = asyncio.create_task(_background(database, broker, log))

        async def callback(incoming: AbstractIncomingMessage) -> None:
            await _on_message(database, settings, incoming)

        await queue.consume(callback)
        log.info("worker_started", queue=COMMAND_CONSUMER)
        await asyncio.Future()
    finally:
        if tick is not None:
            tick.cancel()
        await broker.close()
        await database.close()
        log.info("worker_stopped")


def worker_main(settings_factory: type[Settings]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="store_true",
        help="Start connectivity monitor (no business consumers)",
    )
    parser.add_argument(
        "--consume",
        action="store_true",
        help="Start payment command consumer and outbox publisher",
    )
    parser.add_argument("--once", action="store_true", help="Check broker once and exit")
    args = parser.parse_args()
    settings = settings_factory()
    if args.consume:
        try:
            asyncio.run(run_business(settings))
            return 0
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(
                f"Worker stopped ({type(exc).__name__}); verify database and broker configuration"
            )
            return 1
    if args.run:
        try:
            asyncio.run(monitor(settings, once=args.once))
            return 0
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"Worker stopped ({type(exc).__name__}); verify broker configuration")
            return 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(worker_main(Settings))
