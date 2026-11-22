"""Fixed Order routes; identity is verified by Order, not forged headers."""

from typing import Literal
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from commerce_backend_common.errors import ServiceError

router = APIRouter(prefix="/api/v1")


async def _forward(request: Request, path: str, *, admin_list: bool = False) -> JSONResponse:
    authorization = request.headers.get("authorization", "")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ServiceError(401, "AUTH_INVALID", "Authentication required")
    headers = {"Authorization": authorization, "X-Request-Id": request.state.request_id}
    if key := request.headers.get("Idempotency-Key"):
        headers["Idempotency-Key"] = key
    content: bytes | None = None
    if request.method == "POST":
        content_type = (
            request.headers.get("content-type", "application/json").split(";", 1)[0].strip().lower()
        )
        if content_type != "application/json":
            raise ServiceError(400, "VALIDATION_ERROR", "Expected a JSON request body")
        headers["Content-Type"] = "application/json"
        content = await request.body()
    allowed = {"page", "pageSize", "status"}
    if admin_list:
        allowed.add("q")
    params = [(key, value) for key, value in request.query_params.multi_items() if key in allowed]
    client: httpx.AsyncClient = request.app.state.order_client
    try:
        upstream = await client.request(
            request.method, path, headers=headers, params=urlencode(params), content=content
        )
    except httpx.RequestError as exc:
        raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Order service is unavailable") from exc
    if upstream.status_code not in {200, 202, 400, 401, 403, 404, 409, 429, 500, 503}:
        raise ServiceError(502, "UPSTREAM_INVALID_RESPONSE", "Unexpected Order response")
    try:
        body = upstream.json()
    except ValueError as exc:
        raise ServiceError(502, "UPSTREAM_INVALID_RESPONSE", "Invalid Order response") from exc
    if not isinstance(body, dict):
        raise ServiceError(502, "UPSTREAM_INVALID_RESPONSE", "Invalid Order response")
    if upstream.status_code >= 400:
        if not isinstance(body.get("code"), str) or not isinstance(body.get("message"), str):
            raise ServiceError(502, "UPSTREAM_INVALID_RESPONSE", "Invalid Order error response")
        body = {key: value for key, value in body.items() if key in {"code", "message", "details"}}
        body["requestId"] = request.state.request_id
    return JSONResponse(
        body, status_code=upstream.status_code, headers={"Cache-Control": "no-store"}
    )


@router.post("/orders/quote")
async def order_quote(request: Request) -> JSONResponse:
    return await _forward(request, "/api/v1/orders/quote")


@router.post("/orders")
async def create_order(request: Request) -> JSONResponse:
    return await _forward(request, "/api/v1/orders")


@router.get("/orders")
async def orders(request: Request) -> JSONResponse:
    return await _forward(request, "/api/v1/orders")


@router.get("/orders/{id}")
async def order_detail(id: UUID, request: Request) -> JSONResponse:
    return await _forward(request, f"/api/v1/orders/{id}")


@router.get("/admin/orders")
async def admin_orders(request: Request) -> JSONResponse:
    return await _forward(request, "/api/v1/admin/orders", admin_list=True)


@router.get("/admin/orders/{id}")
async def admin_order_detail(id: UUID, request: Request) -> JSONResponse:
    return await _forward(request, f"/api/v1/admin/orders/{id}")


@router.post("/orders/{id}/cancel")
async def cancel_order(id: UUID, request: Request) -> JSONResponse:
    return await _forward(request, f"/api/v1/orders/{id}/cancel")


@router.post("/admin/orders/{id}/{action}")
async def admin_order_action(
    id: UUID,
    action: Literal["confirm", "cancel", "dispatch", "complete", "exceptions"],
    request: Request,
) -> JSONResponse:
    return await _forward(request, f"/api/v1/admin/orders/{id}/{action}")
