"""inventory-service configuration, with an explicit service-local env file."""

from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from commerce_backend_common.database import DatabaseSettings


class Settings(DatabaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[2] / ".env")
    service_name: Literal["inventory-service"] = "inventory-service"
    http_port: int = Field(default=3003, ge=1024, le=65535)
    db_schema: Literal["commerce_inventory"] = "commerce_inventory"

    identity_base_url: HttpUrl = HttpUrl("http://127.0.0.1:3001")
    catalog_base_url: HttpUrl = HttpUrl("http://127.0.0.1:3002")
    catalog_service_token: SecretStr | None = None
    inventory_order_token: SecretStr | None = None
    inventory_catalog_token: SecretStr | None = None

    @model_validator(mode="after")
    def distinct_internal_credentials(self) -> "Settings":
        if (
            self.inventory_order_token is not None
            and self.inventory_catalog_token is not None
            and self.inventory_order_token.get_secret_value()
            == self.inventory_catalog_token.get_secret_value()
        ):
            raise ValueError("Order and Catalog must use distinct Inventory service credentials")
        return self

    @field_validator("identity_base_url", "catalog_base_url")
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
            "catalog-service",
        }:
            raise ValueError("Cross-host upstream connections require HTTPS")
        return value
