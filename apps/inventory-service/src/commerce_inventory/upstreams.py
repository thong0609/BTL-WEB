"""Identity verifies bearer tokens; Catalog verifies external product IDs."""

from typing import Annotated, Literal
from uuid import UUID

import httpx
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ValidationError

from commerce_backend_common.errors import ServiceError
from commerce_inventory.settings import Settings

bearer = HTTPBearer(auto_error=False)


class Principal(BaseModel):
    id: UUID
    role: Literal["ADMIN", "CUSTOMER"]
    status: Literal["ACTIVE", "DISABLED"]


class CatalogProduct(BaseModel):
    id: UUID


class CatalogBatch(BaseModel):
    items: list[CatalogProduct]


def unavailable() -> ServiceError:
    return ServiceError(503, "DEPENDENCY_UNAVAILABLE", "A required service is unavailable")


async def require_admin(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is None:
        raise ServiceError(401, "AUTH_INVALID", "A valid bearer token is required")
    client: httpx.AsyncClient = request.app.state.identity_client
    try:
        response = await client.get(
            "/api/v1/users/me",
            headers={
                "Authorization": f"Bearer {credentials.credentials}",
                "X-Request-Id": request.state.request_id,
            },
        )
    except httpx.RequestError as exc:
        raise unavailable() from exc
    if response.status_code == 401:
        raise ServiceError(401, "AUTH_INVALID", "A valid bearer token is required")
    if response.status_code == 403:
        raise ServiceError(403, "FORBIDDEN", "Administrator access is required")
    if response.status_code != 200:
        raise unavailable()
    try:
        principal = Principal.model_validate_json(response.content)
    except ValidationError as exc:
        raise unavailable() from exc
    if principal.status != "ACTIVE" or principal.role != "ADMIN":
        raise ServiceError(403, "FORBIDDEN", "Administrator access is required")
    return principal


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


def get_catalog(request: Request) -> CatalogClient:
    return CatalogClient(
        request.app.state.catalog_client, request.app.state.settings, request.state.request_id
    )
