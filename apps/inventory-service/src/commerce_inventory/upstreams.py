"""HTTP client adapter for Catalog product lookup."""

from uuid import UUID

import httpx
from pydantic import ValidationError

from commerce_backend_common.errors import ServiceError
from commerce_inventory.schemas import CatalogBatch
from commerce_inventory.settings import Settings


def unavailable() -> ServiceError:
    return ServiceError(503, "DEPENDENCY_UNAVAILABLE", "A required service is unavailable")


class CatalogClient:
    def __init__(self, client: httpx.AsyncClient, settings: Settings, request_id: str):
        self.client = client
        self.settings = settings
        self.request_id = request_id

    async def verify_product(self, product_id: UUID) -> None:
        token = self.settings.catalog_service_token
        if token is None or not token.get_secret_value().strip():
            raise unavailable()
        try:
            response = await self.client.post(
                "/internal/products/batch",
                json={"productIds": [str(product_id)]},
                headers={
                    "Authorization": f"Bearer {token.get_secret_value()}",
                    "X-Request-Id": self.request_id,
                },
            )
        except httpx.RequestError as exc:
            raise unavailable() from exc
        if response.status_code != 200:
            raise unavailable()
        try:
            batch = CatalogBatch.model_validate_json(response.content)
        except ValidationError as exc:
            raise unavailable() from exc
        if not batch.items:
            raise ServiceError(404, "NOT_FOUND", "Catalog product does not exist")
        if len(batch.items) != 1 or batch.items[0].id != product_id:
            raise unavailable()
