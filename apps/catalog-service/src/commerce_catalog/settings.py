"""catalog-service configuration, with an explicit service-local env file."""

import tempfile
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import SettingsConfigDict

from commerce_backend_common.database import DatabaseSettings


class Settings(DatabaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[2] / ".env")
    service_name: Literal["catalog-service"] = "catalog-service"
    http_port: int = Field(default=3002, ge=1024, le=65535)
    db_schema: Literal["commerce_catalog"] = "commerce_catalog"

    identity_base_url: HttpUrl = HttpUrl("http://127.0.0.1:3001")
    catalog_service_token: SecretStr | None = None
    catalog_storage_dir: Path = Field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "commerce-catalog-images"
    )

    @field_validator("identity_base_url")
    @classmethod
    def upstream_origin(cls, value: HttpUrl) -> HttpUrl:
        if (
            value.username
            or value.password
            or value.query
            or value.fragment
            or value.path not in {None, "/"}
        ):
            raise ValueError("Upstream URL must be an HTTP(S) origin without credentials or path")
        if value.scheme != "https" and value.host not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "identity-service",
        }:
            raise ValueError("Cross-host upstream connections require HTTPS")
        return value
