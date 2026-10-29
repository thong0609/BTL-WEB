import pytest


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL",
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
