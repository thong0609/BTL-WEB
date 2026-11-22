"""Order adapter for the proposed Catalog internal batch contract."""

from typing import Annotated, Literal, Self
from uuid import UUID

import httpx
from pydantic import (
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from commerce_backend_common.errors import ServiceError
from commerce_backend_common.schemas import ApiModel
from commerce_order.api.schemas import InputMoney

MAX_BATCH_BYTES = 1024 * 1024


class CatalogProduct(ApiModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=False, validate_by_name=False)
    id: UUID
    sku: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=64)]
    name: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=200)]
    status: Literal["DRAFT", "ACTIVE", "DISCONTINUED"]
    price_amount: InputMoney
    currency: Literal["VND"]
    version: Annotated[int, Field(strict=True, ge=0, le=2147483647)]

    @model_validator(mode="after")
    def nonblank_labels(self) -> Self:
        if not self.sku.strip() or not self.name.strip():
            raise ValueError("Catalog product labels must not be blank")
        return self


class CatalogBatch(ApiModel):
    model_config = ConfigDict(extra="ignore")
    items: list[CatalogProduct] = Field(max_length=50)


class CatalogClient:
    def __init__(self, http: httpx.AsyncClient, service_token: SecretStr | None) -> None:
        self.http = http
        self.service_token = service_token

    async def products(
        self, product_ids: list[UUID], request_id: str
    ) -> dict[UUID, CatalogProduct]:
        if not 1 <= len(product_ids) <= 50 or len(set(product_ids)) != len(product_ids):
            raise ServiceError(400, "VALIDATION_ERROR", "Invalid product batch")
        if self.service_token is None:
            raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Catalog access is not configured")
        try:
            async with self.http.stream(
                "POST",
                "/internal/products/batch",
                json={"productIds": [str(value) for value in product_ids]},
                headers={
                    "Authorization": f"Bearer {self.service_token.get_secret_value()}",
                    "X-Request-Id": request_id,
                },
            ) as response:
                if response.status_code != 200:
                    raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Catalog is unavailable")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_BATCH_BYTES:
                        raise ServiceError(
                            503, "DEPENDENCY_UNAVAILABLE", "Invalid Catalog response"
                        )
                    body.extend(chunk)
            batch = CatalogBatch.model_validate_json(bytes(body))
        except (httpx.HTTPError, ValidationError) as exc:
            raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Catalog is unavailable") from exc
        records = {product.id: product for product in batch.items}
        if len(records) != len(batch.items) or set(records) - set(product_ids):
            raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Invalid Catalog response")
        if set(product_ids) - set(records) or any(
            product.status != "ACTIVE" for product in batch.items
        ):
            # Do not disclose draft/discontinued product names or prices.
            raise ServiceError(404, "NOT_FOUND", "Product is unavailable")
        if len({product.sku for product in batch.items}) != len(batch.items):
            raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Invalid Catalog response")
        return records
