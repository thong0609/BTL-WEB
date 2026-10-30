"""Versioned transport topology matching docs/contracts/MESSAGES.md."""

from aio_pika import ExchangeType
from aio_pika.abc import AbstractRobustChannel

COMMANDS = "commerce.commands"
EVENTS = "commerce.events"
DEAD = "commerce.dead"

COMMAND_ROUTES = {
    "inventory.commands": ("inventory.reserve", "inventory.release", "inventory.commit"),
    "payment.commands": (
        "payment.initialize-cod",
        "payment.process",
        "payment.collect-cod",
        "payment.cancel-cod",
        "payment.refund",
    ),
}
EVENT_ROUTES = (
    "inventory.stock-reserved",
    "inventory.stock-reservation-failed",
    "inventory.stock-released",
    "inventory.stock-release-failed",
    "inventory.stock-committed",
    "inventory.stock-commit-failed",
    "payment.initialized",
    "payment.succeeded",
    "payment.failed",
    "payment.cod-collected",
    "payment.cod-cancelled",
    "payment.refunded",
    "payment.refund-failed",
    "payment.command-rejected",
)
SERVICE_QUEUE = {
    "inventory-service": "inventory.commands",
    "payment-service": "payment.commands",
    "order-service": "order.events",
}


async def declare_topology(channel: AbstractRobustChannel, service: str) -> None:
    if service not in SERVICE_QUEUE:
        raise ValueError("This service has no messaging queue in the MVP contract")
    commands = await channel.declare_exchange(COMMANDS, ExchangeType.DIRECT, durable=True)
    events = await channel.declare_exchange(EVENTS, ExchangeType.TOPIC, durable=True)
    dead = await channel.declare_exchange(DEAD, ExchangeType.DIRECT, durable=True)
    name = SERVICE_QUEUE[service]
    dead_name = f"{name}.dead"
    dead_queue = await channel.declare_queue(dead_name, durable=True)
    await dead_queue.bind(dead, routing_key=dead_name)
    queue = await channel.declare_queue(
        name,
        durable=True,
        arguments={"x-dead-letter-exchange": DEAD, "x-dead-letter-routing-key": dead_name},
    )
    exchange = events if service == "order-service" else commands
    keys = EVENT_ROUTES if service == "order-service" else COMMAND_ROUTES[name]
    for key in keys:
        await queue.bind(exchange, routing_key=key)
