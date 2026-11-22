"""order-service configuration, with an explicit service-local env file."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import SettingsConfigDict

from commerce_backend_common.database import DatabaseSettings
from commerce_order.domain.money import PG_BIGINT_MAX, parse_money_string


class Settings(DatabaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env", hide_input_in_errors=True
    )
    service_name: Literal["order-service"] = "order-service"
    http_port: int = Field(default=3004, ge=1024, le=65535)
    db_schema: Literal["commerce_orders"] = "commerce_orders"
    catalog_base_url: HttpUrl = HttpUrl("http://127.0.0.1:3002")
    catalog_service_token: SecretStr | None = None
    inventory_base_url: HttpUrl = HttpUrl("http://127.0.0.1:3003")
    payment_base_url: HttpUrl = HttpUrl("http://127.0.0.1:3005")
    inventory_service_token: SecretStr | None = None
    payment_service_token: SecretStr | None = None
    shipping_fee_amount: int | None = Field(default=None, ge=0, le=PG_BIGINT_MAX)
    order_outbox_batch_size: int = Field(default=20, ge=1, le=100)
    order_outbox_lease_seconds: float = Field(default=60, ge=1, le=3600)
    order_outbox_max_attempts: int = Field(default=10, ge=1, le=100)
    order_worker_poll_seconds: float = Field(default=0.5, ge=0.05, le=60)
    order_recovery_enabled: bool = False
    order_recovery_batch_size: int = Field(default=10, ge=1, le=100)
    order_recovery_stale_seconds: float = Field(default=300, ge=0, le=86400)
    order_recovery_lease_seconds: float = Field(default=60, ge=1, le=3600)
    order_recovery_poll_seconds: float = Field(default=10, ge=0.05, le=3600)
    order_recovery_max_attempts: int = Field(default=5, ge=1, le=100)
    order_event_max_attempts: int = Field(default=4, ge=1, le=20)
    order_event_retry_delays_ms: list[Annotated[int, Field(strict=True, ge=10, le=3600000)]] = (
        Field(default=[1000, 5000, 30000], min_length=1, max_length=10)
    )

    @field_validator("catalog_base_url", "inventory_base_url", "payment_base_url")
    @classmethod
    def catalog_origin(cls, value: HttpUrl) -> HttpUrl:
        if (
            value.username
            or value.password
            or value.query
            or value.fragment
            or value.path not in {None, "/"}
        ):
            raise ValueError("Service URL must be an HTTP(S) origin without credentials or path")
        return value

    @field_validator("shipping_fee_amount", mode="before")
    @classmethod
    def integer_fee(cls, value: object) -> object:
        if value is None or type(value) is int:
            return value
        if isinstance(value, str):
            return parse_money_string(value)
        raise ValueError("Shipping fee must be a nonnegative integer")

    @field_validator("catalog_service_token", "inventory_service_token", "payment_service_token")
    @classmethod
    def service_credential(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            token = value.get_secret_value()
            if not token or len(token) > 4096 or any(not 33 <= ord(char) <= 126 for char in token):
                raise ValueError("Catalog service credential must be a nonempty HTTP bearer token")
        return value
