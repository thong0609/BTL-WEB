"""Trusted headers from gateway or service callers, never end-user identity."""

from uuid import UUID

from fastapi import Request

from commerce_backend_common.errors import ServiceError
from commerce_payment.settings import Settings


def customer_id(request: Request) -> UUID:
    raw = request.headers.get("X-Customer-Id", "").strip()
    try:
        return UUID(raw)
    except ValueError:
        raise ServiceError(401, "AUTH_REQUIRED", "Authentication required") from None


def require_admin(request: Request) -> None:
    if request.headers.get("X-User-Role", "").upper() != "ADMIN":
        raise ServiceError(403, "FORBIDDEN", "Permission denied")


def require_internal(request: Request, settings: Settings) -> None:
    token = settings.internal_service_token
    if token is None:
        raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Internal API is not configured")
    supplied = request.headers.get("X-Internal-Token", "")
    if supplied != token.get_secret_value():
        raise ServiceError(403, "FORBIDDEN", "Permission denied")


def require_demo_admin(request: Request, settings: Settings) -> None:
    require_admin(request)
    if settings.app_env not in {"dev", "test", "demo"}:
        raise ServiceError(404, "NOT_FOUND", "Resource not found")
