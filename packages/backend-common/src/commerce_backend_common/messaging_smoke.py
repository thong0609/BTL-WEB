"""A single probe using UUID-named exclusive resources; never touches business queues."""

from uuid import uuid4

from aio_pika import ExchangeType

from commerce_backend_common.messaging import Broker, BrokerError, MessageEnvelope, parse_envelope


async def smoke_test(broker: Broker) -> str:
    channel = await broker.ready_channel()
    name = f"commerce.smoke.{uuid4().hex}"
    exchange = await channel.declare_exchange(
        name, ExchangeType.DIRECT, durable=False, auto_delete=True, robust=False
    )
    queue = None
    bound = False
    try:
        queue = await channel.declare_queue(
            name, exclusive=True, auto_delete=True, durable=False, robust=False
        )
        await queue.bind(exchange, routing_key="probe", robust=False)
        bound = True
        envelope = MessageEnvelope.new("SmokeProbe", uuid4(), {"probe": True})
        await broker.publish(name, "probe", envelope)
        incoming = await queue.get(
            no_ack=False, timeout=broker.settings.broker_publish_timeout_seconds
        )
        if incoming is None:
            raise BrokerError("Smoke message was not received")
        async with incoming.process(requeue=False):
            received = parse_envelope(incoming.body, broker.settings.broker_max_message_bytes)
            if received != envelope or incoming.message_id != str(envelope.message_id):
                raise BrokerError("Smoke message metadata did not match")
        return name
    finally:
        if queue is not None and not channel.is_closed:
            await queue.delete(if_unused=False, if_empty=False)
        # A bound auto-delete exchange disappears when its final binding is removed.
        if not bound and not channel.is_closed:
            await exchange.delete(if_unused=True)
