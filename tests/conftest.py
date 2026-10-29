import os
import secrets
import subprocess
import time
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL",
        "MIGRATION_DATABASE_URL",
        "DB_SCHEMA",
        "DB_SSL_MODE",
        "DB_SSL_CA_FILE",
        "BROKER_URL",
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
        env.update(TEST_ADMIN_DATABASE_URL=admin_url)
        for prefix in ("IDENTITY", "CATALOG", "INVENTORY", "ORDER", "PAYMENT"):
            for kind in ("RUNTIME", "MIGRATOR"):
                env[f"{prefix}_{kind}_PASSWORD"] = role_password
        yield {"admin_url": admin_url, "password": role_password, "port": port, "env": env}
    finally:
        subprocess.run(["docker", "stop", container], capture_output=True, timeout=30, check=False)
