"""Forward only the four INV-01 routes; Inventory enforces ADMIN authorization."""

from uuid import UUID

import httpx
from fastapi import APIRouter, Request, Response

from commerce_backend_common.errors import ServiceError

router = APIRouter(prefix="/api/v1/admin/inventory", tags=["Inventory"])


async def forward(request: Request, path: str) -> Response:
    client: httpx.AsyncClient = request.app.state.inventory_client
    headers = {"X-Request-Id": request.state.request_id}
    for name in ("Authorization", "Idempotency-Key", "Content-Type"):
        if name in request.headers:
            headers[name] = request.headers[name]
    try:
        response = await client.request(
            request.method,
            "/api/v1/admin/inventory" + path,
            params=request.query_params,
            content=await request.body(),
            headers=headers,
        )
    except httpx.RequestError as exc:
        raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Inventory is unavailable") from exc
    if response.status_code not in {200, 201, 400, 401, 403, 404, 409, 429, 503}:
        raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Inventory is unavailable")
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type="application/json",
    )


@router.get("")
async def list_stock(request: Request) -> Response:
    return await forward(request, "")


@router.post("/items")
async def initialize(request: Request) -> Response:
    return await forward(request, "/items")


@router.post("/adjustments")
async def adjust(request: Request) -> Response:
    return await forward(request, "/adjustments")


@router.get("/{productId}/movements")
async def movements(productId: UUID, request: Request) -> Response:
    return await forward(request, f"/{productId}/movements")
