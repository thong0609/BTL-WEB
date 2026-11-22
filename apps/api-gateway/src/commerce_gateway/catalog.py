"""Forward only the public and ADMIN Catalog routes; Catalog enforces ADMIN authorization."""

import re
from uuid import UUID

import httpx
from fastapi import APIRouter, Request, Response

from commerce_backend_common.errors import ServiceError

router = APIRouter(tags=["Catalog"])
IMAGE_FILE_RE = re.compile(r"^[0-9a-fA-F-]{36}\.(?:jpg|jpeg|png|webp)$")
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


async def forward(
    request: Request,
    path: str,
    *,
    include_auth: bool = False,
    allow_binary_image: bool = False,
) -> Response:
    client: httpx.AsyncClient = request.app.state.catalog_client
    headers = {"X-Request-Id": request.state.request_id}
    allowed_headers = ("Authorization", "Content-Type") if include_auth else ("Content-Type",)
    for name in allowed_headers:
        if name in request.headers:
            headers[name] = request.headers[name]
    try:
        response = await client.request(
            request.method,
            path,
            params=request.query_params,
            content=await request.body(),
            headers=headers,
        )
    except httpx.RequestError as exc:
        raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Catalog is unavailable") from exc
    if response.status_code not in {200, 201, 204, 400, 401, 403, 404, 409, 429, 503}:
        raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Catalog is unavailable")
    if response.status_code == 204:
        return Response(status_code=204)
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    media_type = (
        content_type
        if (allow_binary_image and content_type in ALLOWED_IMAGE_TYPES)
        else "application/json"
    )
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=media_type,
    )


# Public endpoints
@router.get("/api/v1/categories")
async def list_categories(request: Request) -> Response:
    return await forward(request, "/api/v1/categories")


@router.get("/api/v1/products")
async def list_products(request: Request) -> Response:
    return await forward(request, "/api/v1/products")


@router.get("/api/v1/products/{id}")
async def get_product(id: UUID, request: Request) -> Response:
    return await forward(request, f"/api/v1/products/{id}")


@router.get("/api/v1/catalog/images/{productId}/{filename}")
async def get_image(productId: UUID, filename: str, request: Request) -> Response:
    if not IMAGE_FILE_RE.fullmatch(filename):
        raise ServiceError(404, "NOT_FOUND", "Image not found")
    return await forward(
        request,
        f"/api/v1/catalog/images/{productId}/{filename}",
        allow_binary_image=True,
    )


# Admin Category endpoints
@router.get("/api/v1/admin/categories")
async def list_categories_admin(request: Request) -> Response:
    return await forward(request, "/api/v1/admin/categories", include_auth=True)


@router.post("/api/v1/admin/categories")
async def create_category_admin(request: Request) -> Response:
    return await forward(request, "/api/v1/admin/categories", include_auth=True)


@router.patch("/api/v1/admin/categories/{id}")
async def patch_category_admin(id: UUID, request: Request) -> Response:
    return await forward(request, f"/api/v1/admin/categories/{id}", include_auth=True)


# Admin Product endpoints
@router.get("/api/v1/admin/products")
async def list_products_admin(request: Request) -> Response:
    return await forward(request, "/api/v1/admin/products", include_auth=True)


@router.post("/api/v1/admin/products")
async def create_product_admin(request: Request) -> Response:
    return await forward(request, "/api/v1/admin/products", include_auth=True)


@router.get("/api/v1/admin/products/{id}")
async def get_product_admin(id: UUID, request: Request) -> Response:
    return await forward(request, f"/api/v1/admin/products/{id}", include_auth=True)


@router.patch("/api/v1/admin/products/{id}")
async def patch_product_admin(id: UUID, request: Request) -> Response:
    return await forward(request, f"/api/v1/admin/products/{id}", include_auth=True)


# Admin Image endpoints
@router.post("/api/v1/admin/products/{id}/images")
async def upload_image_admin(id: UUID, request: Request) -> Response:
    return await forward(request, f"/api/v1/admin/products/{id}/images", include_auth=True)


@router.delete("/api/v1/admin/products/{id}/images/{imageId}")
async def delete_image_admin(id: UUID, imageId: UUID, request: Request) -> Response:
    return await forward(
        request,
        f"/api/v1/admin/products/{id}/images/{imageId}",
        include_auth=True,
    )
