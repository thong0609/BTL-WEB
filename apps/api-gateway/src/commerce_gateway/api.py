"""A fixed diagnostic upstream route, not a user-selected proxy."""

import httpx
from fastapi import APIRouter, Request
from pydantic import ValidationError

from commerce_backend_common.application import HealthResponse
from commerce_backend_common.errors import ServiceError

router = APIRouter(prefix="/api/v1/health", tags=["diagnostics"])


@router.get("/catalog", response_model=HealthResponse)
async def catalog_health(request: Request) -> HealthResponse:
    client: httpx.AsyncClient = request.app.state.catalog_client
    try:
        response = await client.get(
            "/health/live", headers={"X-Request-Id": request.state.request_id}
        )
    except httpx.TimeoutException as exc:
        raise ServiceError(504, "UPSTREAM_TIMEOUT", "Catalog health check timed out") from exc
    except httpx.RequestError as exc:
        raise ServiceError(503, "UPSTREAM_UNAVAILABLE", "Catalog is unavailable") from exc
    if response.status_code != 200:
        raise ServiceError(502, "UPSTREAM_ERROR", "Catalog health check failed")
    try:
        result = HealthResponse.model_validate_json(response.content)
    except ValidationError as exc:
        raise ServiceError(
            502, "UPSTREAM_INVALID_RESPONSE", "Catalog returned invalid health data"
        ) from exc
    if result.service != "catalog-service" or result.status != "alive":
        raise ServiceError(
            502, "UPSTREAM_INVALID_RESPONSE", "Catalog returned unexpected health data"
        )
    return result
