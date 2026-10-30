import os
import secrets
import socket
import subprocess
import time
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    for name in (
        "DATABASE_URL",
        "MIGRATION_DATABASE_URL",
        "DB_SCHEMA",
        "DB_SSL_MODE",
        "DB_SSL_CA_FILE",
        "BROKER_URL",
        "BROKER_SSL_CA_FILE",
        "BROKER_CONNECT_TIMEOUT_SECONDS",
        "BROKER_PUBLISH_TIMEOUT_SECONDS",
        "SERVICE_NAME",
        "HTTP_PORT",
        "HTTP_HOST",
        "CATALOG_BASE_URL",
        "CORS_ORIGINS",
        "HTTP_TIMEOUT_SECONDS",
        "HTTP_MAX_CONNECTIONS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    monkeypatch.setenv("BROKER_ENABLED", "false")


def pytest_addoption(parser):
    parser.addoption(
        "--run-postgres", action="store_true", help="Run isolated Docker PostgreSQL tests"
    )
    parser.addoption(
        "--run-rabbitmq", action="store_true", help="Run isolated Docker RabbitMQ tests"
    )


@pytest.fixture(scope="session")
def postgres_test(request):
    if not request.config.getoption("--run-postgres"):
        pytest.skip("Use --run-postgres to create an isolated, disposable test database")
    import asyncio

    import asyncpg

    container = "commerce-db-test-" + uuid4().hex[:12]
    password = secrets.token_urlsafe(24)
    result = subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            container,
            "--publish",
            "127.0.0.1::5432",
            "--env",
            "POSTGRES_DB=commerce_test",
            "--env",
            "POSTGRES_USER=postgres",
            "--env",
            f"POSTGRES_PASSWORD={password}",
            "postgres:16",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode:
        pytest.fail("Unable to start PostgreSQL test container; check Docker daemon/image access")
    try:
        binding = subprocess.check_output(
            ["docker", "port", container, "5432/tcp"], text=True, timeout=10
        ).strip()
        port = int(binding.rsplit(":", 1)[1])

        async def wait_ready():
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    connection = await asyncpg.connect(
                        host="127.0.0.1",
                        port=port,
                        database="commerce_test",
                        user="postgres",
                        password=password,
                        ssl=False,
                        timeout=2,
                    )
                    await connection.close()
                    return
                except (OSError, asyncpg.PostgresError):
                    await asyncio.sleep(0.2)
            raise RuntimeError("PostgreSQL test database startup timed out")

        asyncio.run(wait_ready())
        admin_url = f"postgresql+asyncpg://postgres:{password}@127.0.0.1:{port}/commerce_test"
        role_password = secrets.token_urlsafe(24) + "':\\probe"
        env = os.environ.copy()
        env.update(APP_ENV="test", TEST_ADMIN_DATABASE_URL=admin_url)
        for prefix in ("IDENTITY", "CATALOG", "INVENTORY", "ORDER", "PAYMENT"):
            for kind in ("RUNTIME", "MIGRATOR"):
                env[f"{prefix}_{kind}_PASSWORD"] = role_password
        yield {"admin_url": admin_url, "password": role_password, "port": port, "env": env}
    finally:
        subprocess.run(["docker", "stop", container], capture_output=True, timeout=30, check=False)


@pytest.fixture(scope="session")
def rabbitmq_test(request):
    if not request.config.getoption("--run-rabbitmq"):
        pytest.skip("Use --run-rabbitmq for disposable local RabbitMQ integration tests")
    import asyncio

    from commerce_backend_common.messaging import Broker
    from commerce_backend_common.settings import ServiceSettings

    container = "commerce-broker-test-" + uuid4().hex[:12]
    # Pick a loopback port once: Docker's auto-assigned host port may change on restart.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        requested_port = reservation.getsockname()[1]
    password = secrets.token_hex(24)
    env = {**os.environ, "RABBITMQ_DEFAULT_PASS": password}
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--rm",
                "--name",
                container,
                "--publish",
                f"127.0.0.1:{requested_port}:5672",
                "--env",
                "RABBITMQ_DEFAULT_USER=commerce_test",
                "--env",
                "RABBITMQ_DEFAULT_PASS",
                "--env",
                "RABBITMQ_DEFAULT_VHOST=commerce_test",
                "rabbitmq:4-alpine",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode:
            pytest.fail("RabbitMQ test container could not start; check Docker/image access")
        binding = subprocess.check_output(
            ["docker", "port", container, "5672/tcp"], text=True, timeout=10
        ).strip()
        port = int(binding.rsplit(":", 1)[1])
        url = f"amqp://commerce_test:{password}@127.0.0.1:{port}/commerce_test"

        async def wait_ready():
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                settings = ServiceSettings(
                    service_name="broker-test",
                    http_port=3099,
                    broker_url=url,
                    broker_connect_timeout_seconds=1,
                )
                broker = Broker(settings, role="test-startup")
                try:
                    await broker.open()
                    return
                except Exception:
                    await asyncio.sleep(0.5)
                finally:
                    await broker.close()
            raise RuntimeError("RabbitMQ test startup timed out")

        asyncio.run(wait_ready())
        yield {"url": url, "container": container, "password": password}
    finally:
        subprocess.run(["docker", "stop", container], capture_output=True, timeout=30, check=False)
