"""Separate worker base. Connectivity monitoring only until business handlers exist."""

import argparse
import asyncio

import structlog

from commerce_backend_common.logging import configure_logging
from commerce_backend_common.messaging import Broker, BrokerConfigurationError, BrokerError
from commerce_backend_common.settings import ServiceSettings


async def monitor(settings: ServiceSettings, *, once: bool = False) -> None:
    if not settings.broker_enabled:
        raise BrokerConfigurationError("Enable BROKER_ENABLED explicitly before running the worker")
    configure_logging()
    broker = Broker(settings, role="worker-monitor")
    log = structlog.get_logger().bind(
        service=settings.service_name, mode="connectivity_only", consumers=0
    )
    try:
        await broker.open()
        previous = None
        while True:
            status = await broker.readiness()
            if status != previous:
                log.info("worker_broker_status", status=status)
                previous = status
            if once:
                if status != "ready":
                    raise BrokerError("Worker broker is unavailable")
                return
            await asyncio.sleep(5)
    finally:
        await broker.close()
        log.info("worker_stopped")


def worker_main(settings_factory: type[ServiceSettings]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", action="store_true", help="Start connectivity monitor; no business consumers"
    )
    parser.add_argument("--once", action="store_true", help="Check once and exit")
    args = parser.parse_args()
    if not args.run:
        parser.print_help()
        return 0
    try:
        asyncio.run(monitor(settings_factory(), once=args.once))
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"Worker stopped ({type(exc).__name__}); verify broker configuration")
        return 1
