"""HTTP authentication, idempotency keys and database/client dependencies."""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from commerce_backend_common.database import Database
from commerce_backend_common.errors import ServiceError
from commerce_inventory.schemas import Principal
from commerce_inventory.settings import Settings
from commerce_inventory.upstreams import CatalogClient, unavailable

bearer = HTTPBearer(auto_error=False)


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


async def require_service(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    if credentials is None:
        raise ServiceError(401, "AUTH_INVALID", "A service bearer token is required")
    settings: Settings = request.app.state.settings
    callers = {"order": settings.inventory_order_token, "catalog": settings.inventory_catalog_token}
    caller = None
    for name, token in callers.items():
        if (
            token is not None
            and token.get_secret_value().strip()
            and secrets.compare_digest(
                credentials.credentials.encode(), token.get_secret_value().encode()
            )
        ):
            caller = name
    if caller is None:
        raise ServiceError(401, "AUTH_INVALID", "Invalid service credential")
    return caller


async def require_order(caller: Annotated[str, Depends(require_service)]) -> None:
    if caller != "order":
        raise ServiceError(403, "FORBIDDEN", "This route requires the Order service")


Admin = Annotated[Principal, Depends(require_admin)]


@asynccontextmanager
async def _database_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database | None = request.app.state.database
    if database is None:
        raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Inventory database is unavailable")
    try:
        async with database.session() as session:
            yield session
    except (SQLAlchemyError, TimeoutError) as exc:
        raise ServiceError(
            503, "DEPENDENCY_UNAVAILABLE", "Inventory database is unavailable"
        ) from exc


async def inventory_session(request: Request, admin: Admin) -> AsyncIterator[AsyncSession]:
    # Authentication completes before checking DB configuration or acquiring a connection.
    async with _database_session(request) as session:
        yield session


async def internal_session(
    request: Request, caller: Annotated[str, Depends(require_service)]
) -> AsyncIterator[AsyncSession]:
    async with _database_session(request) as session:
        yield session


def idempotency_key(
    value: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> str:
    if not value.strip():
        raise ServiceError(400, "VALIDATION_ERROR", "Idempotency-Key must not be blank")
    return value


def get_catalog(request: Request) -> CatalogClient:
    return CatalogClient(
        request.app.state.catalog_client, request.app.state.settings, request.state.request_id
    )


AdminSession = Annotated[AsyncSession, Depends(inventory_session)]
InternalSession = Annotated[AsyncSession, Depends(internal_session)]
Key = Annotated[str, Depends(idempotency_key)]
