import importlib
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

SERVICES = [
    ("commerce_gateway", "api-gateway", 3000),
    ("commerce_identity", "identity-service", 3001),
    ("commerce_catalog", "catalog-service", 3002),
    ("commerce_inventory", "inventory-service", 3003),
    ("commerce_order", "order-service", 3004),
    ("commerce_payment", "payment-service", 3005),
]


@pytest.mark.parametrize("module,name,port", SERVICES)
def test_service_factory_lifecycle(module, name, port):
    settings_cls = importlib.import_module(f"{module}.settings").Settings
    factory = importlib.import_module(f"{module}.main").create_app
    settings = settings_cls(_env_file=None)
    assert settings.http_port == port
    app = factory(settings)
    other_app = factory(settings)
    request_id = str(uuid4())
    with TestClient(app) as client:
        assert app.state.started and not other_app.state.started
        response = client.get("/health/live", headers={"X-Request-Id": request_id})
        assert response.json() == {"service": name, "status": "alive", "checks": {}}
        assert response.headers["x-request-id"] == request_id
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["checks"] == {
            "lifespan": "ready",
            "database": "disabled",
            "broker": "disabled",
        }
        error = client.get("/no-such-resource?token=do-not-log")
        assert error.status_code == 404
        assert error.json()["code"] == "NOT_FOUND"
        assert error.json()["requestId"] == error.headers["x-request-id"]
        assert UUID(error.json()["requestId"])
    assert not app.state.started
    if module == "commerce_gateway":
        assert app.state.catalog_client.is_closed


@pytest.mark.parametrize("dependency", ["database", "broker"])
@pytest.mark.parametrize("configured", [False, True])
def test_enabled_dependency_is_not_falsely_ready(dependency, configured):
    from commerce_catalog.main import create_app
    from commerce_catalog.settings import Settings

    values = {f"{dependency}_enabled": True}
    if configured:
        values[f"{dependency}_url"] = "secret-placeholder-not-a-real-connection"
    with TestClient(create_app(Settings(_env_file=None, **values))) as client:
        assert client.get("/health/live").status_code == 200
        ready = client.get("/health/ready")
        assert ready.status_code == 503
        assert ready.json()["checks"][dependency] == (
            ("invalid_configuration" if dependency == "database" else "check_not_implemented")
            if configured
            else "missing_configuration"
        )
        assert "secret-placeholder" not in ready.text


def test_settings_validation_and_service_isolation(monkeypatch):
    from commerce_catalog.settings import Settings as CatalogSettings
    from commerce_gateway.settings import Settings as GatewaySettings

    monkeypatch.setenv("HTTP_PORT", "invalid")
    with pytest.raises(ValidationError):
        CatalogSettings(_env_file=None)
    monkeypatch.delenv("HTTP_PORT")
    for kwargs in [{"http_port": 0}, {"cors_origins": ["*"]}, {"http_timeout_seconds": 0}]:
        with pytest.raises(ValidationError):
            CatalogSettings(_env_file=None, **kwargs)
    for url in ["https://user:secret@example.com", "https://example.com/path", "ftp://a.com"]:
        with pytest.raises(ValidationError):
            GatewaySettings(_env_file=None, catalog_base_url=url)
    with pytest.raises(ValidationError):
        CatalogSettings(_env_file=None, service_name="payment-service")


def test_readiness_requires_lifespan():
    from commerce_catalog.main import create_app
    from commerce_catalog.settings import Settings

    response = TestClient(create_app(Settings(_env_file=None))).get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["lifespan"] == "not_started"
