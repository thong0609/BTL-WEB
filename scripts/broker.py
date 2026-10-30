"""Explicit broker diagnostics/topology. Never auto-run from API startup."""

import argparse
import asyncio
import importlib

from commerce_backend_common.messaging import Broker, BrokerConfigurationError
from commerce_backend_common.messaging_smoke import smoke_test
from commerce_backend_common.messaging_topology import SERVICE_QUEUE, declare_topology
from commerce_backend_common.settings import ServiceSettings


async def execute(action: str, settings: ServiceSettings) -> None:
    if not settings.broker_enabled:
        raise BrokerConfigurationError("BROKER_ENABLED must be true for explicit broker commands")
    broker = Broker(settings, role=f"cli-{action}")
    try:
        await broker.open()
        if action == "topology":
            await declare_topology(await broker.ready_channel(), settings.service_name)
            print(f"Topology declared for {settings.service_name}; no consumer started")
        elif action == "smoke":
            name = await smoke_test(broker)
            print(f"Smoke passed; temporary resources cleaned: {name}")
        else:
            if await broker.readiness() != "ready":
                raise BrokerConfigurationError("Broker check did not succeed")
            print(f"Broker ready: {settings.service_name}")
    finally:
        await broker.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "topology", "smoke"])
    parser.add_argument("--service", choices=list(SERVICE_QUEUE), required=True)
    parser.add_argument(
        "--apply", action="store_true", help="Allow topology or temporary smoke resources"
    )
    args = parser.parse_args()
    if args.action != "check" and not args.apply:
        parser.error("topology/smoke require --apply")
    try:
        module = "commerce_" + args.service.split("-", 1)[0]
        settings: ServiceSettings = importlib.import_module(f"{module}.settings").Settings()
        asyncio.run(execute(args.action, settings))
        return 0
    except Exception as exc:
        print(f"Broker operation failed ({type(exc).__name__}); no credentials or payloads logged")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
