"""Identity verification for ADMIN routes and service bearer check for internal routes."""

import secrets
from typing import Annotated, Literal
from uuid import UUID

import httpx
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ValidationError

from commerce_backend_common.errors import ServiceError
from commerce_catalog.settings import Settings

bearer = HTTPBearer(auto_error=False)


class Principal(BaseModel):
    id: UUID
    role: Literal["ADMIN", "CUSTOMER"]
    status: Literal["ACTIVE", "DISABLED"]


def unavailable() -> ServiceError:
    return ServiceError(503, "DEPENDENCY_UNAVAILABLE", "A required service is unavailable")


async def require_admin(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is None or not credentials.credentials.strip():
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


async def require_internal_service(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    if credentials is None or not credentials.credentials.strip():
        raise ServiceError(401, "AUTH_INVALID", "A valid service bearer token is required")
    settings: Settings = request.app.state.settings
    expected = settings.catalog_service_token
    if expected is None or not expected.get_secret_value().strip():
        raise unavailable()
    if not secrets.compare_digest(credentials.credentials, expected.get_secret_value()):
        raise ServiceError(403, "FORBIDDEN", "Caller is not allowed to access this endpoint")
