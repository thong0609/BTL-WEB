"""api-gateway configuration, with an explicit service-local env file."""

from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import SettingsConfigDict

from commerce_backend_common.settings import ServiceSettings


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[2] / ".env")
    service_name: Literal["api-gateway"] = "api-gateway"
    http_port: int = Field(default=3000, ge=1024, le=65535)

    catalog_base_url: HttpUrl = HttpUrl("http://127.0.0.1:3002")

    @field_validator("catalog_base_url")
    @classmethod
    def validate_catalog_origin(cls, value: HttpUrl) -> HttpUrl:
        if (
            value.username
            or value.password
            or value.query
            or value.fragment
            or value.path not in {None, "/"}
        ):
            raise ValueError("Catalog URL must be an HTTP(S) origin without credentials or path")
        return value
