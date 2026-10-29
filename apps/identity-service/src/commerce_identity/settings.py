"""identity-service configuration, with an explicit service-local env file."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from commerce_backend_common.settings import ServiceSettings


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[2] / ".env")
    service_name: Literal["identity-service"] = "identity-service"
    http_port: int = Field(default=3001, ge=1024, le=65535)
