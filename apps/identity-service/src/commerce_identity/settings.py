"""identity-service configuration, with an explicit service-local env file."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import SettingsConfigDict

from commerce_backend_common.database import DatabaseSettings


class Settings(DatabaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[2] / ".env")
    service_name: Literal["identity-service"] = "identity-service"
    http_port: int = Field(default=3001, ge=1024, le=65535)
    db_schema: Literal["commerce_identity"] = "commerce_identity"

    # Authentication. Secrets are optional here: values are validated and used by
    # the code that wires the auth modules, not by this class.
    jwt_issuer: str = Field(default="commerce-identity-service", min_length=1)
    jwt_private_key_pem: SecretStr | None = None
    oauth_cookie_secret: SecretStr | None = None
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str | None = None
