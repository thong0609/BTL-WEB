import asyncio
import json
import os
import subprocess
import sys
from uuid import uuid4

import pytest
from aio_pika import DeliveryMode, ExchangeType
from aio_pika.exceptions import ChannelNotFoundEntity
from pydantic import ValidationError

from commerce_backend_common.messaging import (
    Broker,
    BrokerConfigurationError,
    BrokerError,
    BrokerUnavailable,
    MessageEnvelope,
    MessageUnroutable,
    broker_url,
    parse_envelope,
)
from commerce_backend_common.messaging_smoke import smoke_test
from commerce_backend_common.messaging_topology import (
    COMMAND_ROUTES,
    COMMANDS,
    EVENT_ROUTES,
    EVENTS,
    SERVICE_QUEUE,
    declare_topology,
)
from commerce_backend_common.settings import ServiceSettings


def config(url, **kwargs):
    return ServiceSettings(service_name="transport-test", http_port=3099, broker_url=url, **kwargs)


def test_envelope_roundtrip_and_compatible_extra_fields():
    envelope = MessageEnvelope.new("SmokeProbe", uuid4(), {"probe": True})
    data = json.loads(envelope.model_dump_json())
    assert data["type"] == "SmokeProbe" and "messageType" not in data
    assert data["occurredAt"].endswith("Z")
    data["futureOptionalField"] = "compatible"
    assert parse_envelope(json.dumps(data).encode()) == envelope


@pytest.mark.parametrize("version", [True, "1", 2])
def test_unknown_or_invalid_version_is_rejected(version):
    data = json.loads(MessageEnvelope.new("SmokeProbe", uuid4(), {}).model_dump_json())
    data["version"] = version
    with pytest.raises(ValidationError):
        parse_envelope(json.dumps(data).encode())


def test_missing_metadata_and_oversized_message_are_rejected():
    with pytest.raises(ValidationError):
        parse_envelope(b'{"payload": {}}')
    with pytest.raises(BrokerError):
        parse_envelope(b"a" * 1025, max_bytes=1024)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "amqp://localhost",
        "amqp://user:secret@localhost/?heartbeat=1",
        "amqp://user:secret@localhost/#fragment",
        "not-a-url",
    ],
)
def test_invalid_url_errors_are_sanitized(url):
    with pytest.raises(BrokerConfigurationError) as failure:
        broker_url(config(url))
    assert "secret" not in str(failure.value)


def test_unavailable_connection_is_not_silently_accepted(capsys):
    async def run():
        broker = Broker(
            config("amqp://user:secret-value@127.0.0.1:1/", broker_connect_timeout_seconds=0.2)
        )
        try:
            with pytest.raises(BrokerUnavailable):
                await broker.open()
            assert await broker.readiness() == "unavailable"
        finally:
            await broker.close()

    asyncio.run(run())
    assert "secret-value" not in capsys.readouterr().out


@pytest.mark.parametrize("service", ["inventory", "order", "payment"])
def test_api_broker_configuration_does_not_spawn_workers(service):
    from importlib import import_module

    from fastapi.testclient import TestClient

    settings_cls = import_module(f"commerce_{service}.settings").Settings
    factory = import_module(f"commerce_{service}.main").create_app
    settings = settings_cls(
        _env_file=None,
        database_enabled=False,
        broker_enabled=True,
        broker_url="amqp://user:secret-value@127.0.0.1:1/",
        broker_connect_timeout_seconds=0.2,
    )
    app = factory(settings)
    with TestClient(app) as client:
        assert app.state.broker.connection is None
        assert client.get("/health/live").status_code == 200
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["checks"]["broker"] == "unavailable"
        assert "secret-value" not in response.text
    assert app.state.broker is None


def test_cli_requires_apply_and_worker_is_opt_in():
    result = subprocess.run(
        [sys.executable, "scripts/broker.py", "topology", "--service", "order-service"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "--apply" in result.stderr
    result = subprocess.run(
        [sys.executable, "-m", "commerce_order.worker"], capture_output=True, text=True
    )
    assert result.returncode == 0 and "--run" in result.stdout


@pytest.mark.integration
def test_rabbitmq_routing_ack_deadletter_smoke_and_cleanup(rabbitmq_test):
    async def run():
        broker = Broker(config(rabbitmq_test["url"]))
        try:
            await broker.open()
            channel = await broker.ready_channel()
            for service in SERVICE_QUEUE:
                await declare_topology(channel, service)
                await declare_topology(channel, service)
            # No business consumer exists; test messages are read only inside this isolated broker.
            for name, keys in COMMAND_ROUTES.items():
                queue = await channel.get_queue(name)
                assert queue.declaration_result.consumer_count == 0
                for key in keys:
                    probe = MessageEnvelope.new("TransportProbe", uuid4(), {"key": key})
                    await broker.publish(COMMANDS, key, probe)
                    message = await queue.get(no_ack=False, timeout=5)
                    assert message.delivery_mode == DeliveryMode.PERSISTENT
                    assert parse_envelope(message.body) == probe
                    await message.ack()
            events = await channel.get_queue("order.events")
            for key in EVENT_ROUTES:
                await broker.publish(
                    EVENTS, key, MessageEnvelope.new("TransportProbe", uuid4(), {})
                )
                message = await events.get(no_ack=False, timeout=5)
                await message.ack()
            with pytest.raises(MessageUnroutable):
                await broker.publish(
                    COMMANDS, "not.bound", MessageEnvelope.new("TransportProbe", uuid4(), {})
                )
            inv = await channel.get_queue("inventory.commands")
            await broker.publish(
                COMMANDS, "inventory.reserve", MessageEnvelope.new("TransportProbe", uuid4(), {})
            )
            rejected = await inv.get(no_ack=False, timeout=5)
            await rejected.reject(requeue=False)
            dead = await channel.get_queue("inventory.commands.dead")
            dead_message = await dead.get(no_ack=False, timeout=5)
            assert dead_message.headers["x-death"]
            await dead_message.ack()
            # Closing a separate unacked channel must redeliver, not lose, its message.
            name = "commerce.smoke." + uuid4().hex
            exchange = await channel.declare_exchange(
                name, ExchangeType.DIRECT, auto_delete=False, robust=False
            )
            queue = await channel.declare_queue(
                name, exclusive=True, auto_delete=True, robust=False
            )
            await queue.bind(exchange, "probe", robust=False)
            await broker.publish(name, "probe", MessageEnvelope.new("RedeliveryProbe", uuid4(), {}))
            auxiliary = await broker.connection.channel()
            aux_queue = await auxiliary.get_queue(name)
            unacked = await aux_queue.get(no_ack=False, timeout=5)
            await auxiliary.close()
            redelivered = await queue.get(no_ack=False, timeout=5)
            assert redelivered.redelivered
            assert redelivered.message_id == unacked.message_id
            await redelivered.ack()
            await queue.delete(if_unused=False, if_empty=False)
            await exchange.delete(if_unused=True)
            cleaned_name = await smoke_test(broker)
            # Passive query on its own channel: missing resources must not break publisher channel.
            probe_channel = await broker.connection.channel()
            with pytest.raises(ChannelNotFoundEntity):
                await probe_channel.get_queue(cleaned_name, ensure=True)
            await probe_channel.close()
        finally:
            await broker.close()
        assert broker.connection.is_closed

    asyncio.run(run())


@pytest.mark.integration
def test_broker_reconnect_after_server_restart(rabbitmq_test):
    async def run():
        broker = Broker(config(rabbitmq_test["url"], broker_publish_timeout_seconds=20))
        try:
            await broker.open()
            await declare_topology(await broker.ready_channel(), "inventory-service")
            probe = MessageEnvelope.new("DurableProbe", uuid4(), {})
            await broker.publish(COMMANDS, "inventory.reserve", probe)
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "restart", rabbitmq_test["container"]],
                capture_output=True,
                text=True,
                timeout=45,
            )
            assert result.returncode == 0
            deadline = asyncio.get_running_loop().time() + 45
            while await broker.readiness() != "ready":
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.5)
            queue = await (await broker.ready_channel()).get_queue("inventory.commands")
            restored = await queue.get(no_ack=False, timeout=5)
            assert restored.message_id == str(probe.message_id)
            await restored.ack()
            assert (await smoke_test(broker)).startswith("commerce.smoke.")
        finally:
            await broker.close()

    asyncio.run(run())


@pytest.mark.integration
def test_real_api_and_worker_monitor_have_zero_consumers(rabbitmq_test):
    from fastapi.testclient import TestClient

    from commerce_order.main import create_app
    from commerce_order.settings import Settings

    app = create_app(
        Settings(
            _env_file=None,
            database_enabled=False,
            broker_enabled=True,
            broker_url=rabbitmq_test["url"],
        )
    )
    with TestClient(app) as client:
        assert client.get("/health/ready").json()["checks"]["broker"] == "ready"
        broker = app.state.broker
    assert broker.connection.is_closed
    env = {
        **os.environ,
        "DATABASE_ENABLED": "false",
        "BROKER_ENABLED": "true",
        "BROKER_URL": rabbitmq_test["url"],
    }
    result = subprocess.run(
        [sys.executable, "-m", "commerce_order.worker", "--run", "--once"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0
    assert '"consumers": 0' in result.stdout
    assert rabbitmq_test["password"] not in result.stdout + result.stderr
