"""Technical settings shared by service-specific settings classes."""

import os
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_file_encoding="utf-8")

    def __init__(self, **values: Any) -> None:
        # Subprocess tests must never discover service-local developer secrets.
        if os.getenv("APP_ENV") == "test" or values.get("app_env") == "test":
            values["_env_file"] = None
        super().__init__(**values)

    service_name: str = Field(min_length=1)
    http_port: int = Field(ge=1024, le=65535)
    http_host: Literal["127.0.0.1", "0.0.0.0"] = "127.0.0.1"
    app_env: str = "dev"
    cors_origins: list[str] = ["http://localhost:3100"]
    http_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    http_max_connections: int = Field(default=20, ge=1, le=100)
    readiness_timeout_seconds: float = Field(default=6, gt=0, le=30)
    database_enabled: bool = False
    broker_enabled: bool = False
    database_url: SecretStr | None = None
    broker_url: SecretStr | None = None
    broker_connect_timeout_seconds: float = Field(default=5, gt=0, le=30)
    broker_publish_timeout_seconds: float = Field(default=5, gt=0, le=30)
    broker_reconnect_interval_seconds: float = Field(default=2, gt=0, le=30)
    broker_prefetch_count: int = Field(default=10, ge=1, le=100)
    broker_heartbeat_seconds: int = Field(default=30, ge=5, le=300)
    broker_max_message_bytes: int = Field(default=262144, ge=1024, le=1048576)
    broker_ssl_ca_file: Path | None = None

    @model_validator(mode="after")
    def validate_origins(self) -> Self:
        if "*" in self.cors_origins:
            raise ValueError("Use explicit CORS origins with credentialed requests")
        return self
