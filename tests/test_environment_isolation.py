import pytest
from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from commerce_backend_common.database import DatabaseConfigurationError, postgres_url
from commerce_backend_common.messaging import BrokerConfigurationError, broker_url
from commerce_backend_common.settings import ServiceSettings


def test_test_settings_ignore_developer_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_ENABLED=true\nDATABASE_URL=must-not-load\nBROKER_ENABLED=true\n")

    class Settings(ServiceSettings):
        model_config = SettingsConfigDict(env_file=env_file)
        service_name: str = "test-service"
        http_port: int = 3099

    monkeypatch.delenv("DATABASE_ENABLED", raising=False)
    monkeypatch.delenv("BROKER_ENABLED", raising=False)
    settings = Settings()
    assert settings.database_enabled is False and settings.database_url is None
    assert settings.broker_enabled is False


def test_remote_database_is_forbidden_in_tests():
    with pytest.raises(DatabaseConfigurationError):
        postgres_url(SecretStr("postgresql://catalog_runtime:secret@db.example.com/postgres"))


def test_remote_broker_is_forbidden_in_tests():
    with pytest.raises(BrokerConfigurationError):
        broker_url(
            ServiceSettings(
                service_name="test",
                http_port=3099,
                broker_url="amqps://user:secret@broker.example.com/dev",
            )
        )
