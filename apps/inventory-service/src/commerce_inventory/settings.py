"""inventory-service configuration, with an explicit service-local env file."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from commerce_backend_common.database import DatabaseSettings


class Settings(DatabaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[2] / ".env")
    service_name: Literal["inventory-service"] = "inventory-service"
    http_port: int = Field(default=3003, ge=1024, le=65535)
    db_schema: Literal["commerce_inventory"] = "commerce_inventory"
