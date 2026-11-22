"""Catalog HTTP API – public, admin, and internal endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from commerce_backend_common.database import Database
from commerce_backend_common.errors import ServiceError
from commerce_catalog import service
from commerce_catalog.schemas import (
    CategoryInput,
    CategoryOut,
    CategoryPatch,
    ImageOut,
    InternalBatch,
    InternalBatchRequest,
    Page,
    ProductInput,
    ProductOut,
    ProductPatch,
    ProductStatus,
    SortOrder,
)
from commerce_catalog.settings import Settings
from commerce_catalog.upstreams import Principal, require_admin, require_internal_service

Admin = Annotated[Principal, Depends(require_admin)]
InternalAuth = Annotated[None, Depends(require_internal_service)]
PageNumber = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(alias="pageSize", ge=1, le=100)]


@asynccontextmanager
async def open_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database | None = request.app.state.database
    if database is None:
        raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Catalog database is unavailable")
    try:
        async with database.session() as session:
            yield session
    except (SQLAlchemyError, TimeoutError) as exc:
        raise ServiceError(
            503, "DEPENDENCY_UNAVAILABLE", "Catalog database is unavailable"
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Public catalog routes
# ─────────────────────────────────────────────────────────────────────────────

public_router = APIRouter(prefix="/api/v1", tags=["Catalog Public"])


@public_router.get("/categories", response_model=Page[CategoryOut])
async def list_categories_public(
    request: Request,
    page: PageNumber = 1,
    page_size: PageSize = 20,
) -> Page[CategoryOut]:
    async with open_db_session(request) as session:
        return await service.list_categories_public(session, page, page_size)


@public_router.get("/products", response_model=Page[ProductOut])
async def list_products_public(
    request: Request,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    q: Annotated[str | None, Query(max_length=200)] = None,
    category_id: Annotated[UUID | None, Query(alias="categoryId")] = None,
    min_price: Annotated[str | None, Query(alias="minPrice", pattern=r"^[0-9]+$")] = None,
    max_price: Annotated[str | None, Query(alias="maxPrice", pattern=r"^[0-9]+$")] = None,
    sort: Annotated[SortOrder | None, Query()] = None,
) -> Page[ProductOut]:
    min_p, max_p = service.parse_price_query(min_price, max_price)
    async with open_db_session(request) as session:
        return await service.list_products(
            session,
            admin=False,
            q=q,
            category_id=category_id,
            min_price=min_p,
            max_price=max_p,
            status=None,
            sort=sort,
            page=page,
            page_size=page_size,
        )


@public_router.get("/products/{id}", response_model=ProductOut)
async def get_product_public(
    id: UUID,
    request: Request,
) -> ProductOut:
    async with open_db_session(request) as session:
        return await service.get_product(session, id, admin=False)


@public_router.get("/catalog/images/{path:path}")
async def get_image(path: str, request: Request) -> FileResponse:
    settings: Settings = request.app.state.settings
    file_path, mime_type = service.get_image_file(path, settings.catalog_storage_dir)
    return FileResponse(file_path, media_type=mime_type)


# ─────────────────────────────────────────────────────────────────────────────
# Admin catalog routes
# ─────────────────────────────────────────────────────────────────────────────

admin_router = APIRouter(prefix="/api/v1/admin", tags=["Catalog Admin"])


@admin_router.get("/categories", response_model=Page[CategoryOut])
async def list_categories_admin(
    request: Request,
    _admin: Admin,
    page: PageNumber = 1,
    page_size: PageSize = 20,
) -> Page[CategoryOut]:
    async with open_db_session(request) as session:
        return await service.list_categories_admin(session, page, page_size)


@admin_router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(
    body: CategoryInput,
    request: Request,
    _admin: Admin,
) -> CategoryOut:
    async with open_db_session(request) as session:
        return await service.create_category(session, body)


@admin_router.patch("/categories/{id}", response_model=CategoryOut)
async def patch_category(
    id: UUID,
    body: CategoryPatch,
    request: Request,
    _admin: Admin,
) -> CategoryOut:
    async with open_db_session(request) as session:
        return await service.patch_category(session, id, body)


@admin_router.get("/products", response_model=Page[ProductOut])
async def list_products_admin(
    request: Request,
    _admin: Admin,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    q: Annotated[str | None, Query(max_length=200)] = None,
    category_id: Annotated[UUID | None, Query(alias="categoryId")] = None,
    min_price: Annotated[str | None, Query(alias="minPrice", pattern=r"^[0-9]+$")] = None,
    max_price: Annotated[str | None, Query(alias="maxPrice", pattern=r"^[0-9]+$")] = None,
    sort: Annotated[SortOrder | None, Query()] = None,
    status: Annotated[ProductStatus | None, Query()] = None,
) -> Page[ProductOut]:
    min_p, max_p = service.parse_price_query(min_price, max_price)
    async with open_db_session(request) as session:
        return await service.list_products(
            session,
            admin=True,
            q=q,
            category_id=category_id,
            min_price=min_p,
            max_price=max_p,
            status=status,
            sort=sort,
            page=page,
            page_size=page_size,
        )


@admin_router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(
    body: ProductInput,
    request: Request,
    _admin: Admin,
) -> ProductOut:
    async with open_db_session(request) as session:
        return await service.create_product(session, body)


@admin_router.get("/products/{id}", response_model=ProductOut)
async def get_product_admin(
    id: UUID,
    request: Request,
    _admin: Admin,
) -> ProductOut:
    async with open_db_session(request) as session:
        return await service.get_product(session, id, admin=True)


@admin_router.patch("/products/{id}", response_model=ProductOut)
async def patch_product(
    id: UUID,
    body: ProductPatch,
    request: Request,
    _admin: Admin,
) -> ProductOut:
    async with open_db_session(request) as session:
        return await service.patch_product(session, id, body)


@admin_router.post(
    "/products/{id}/images",
    response_model=ImageOut,
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "altText": {"type": "string", "maxLength": 255},
                        },
                        "required": ["file"],
                        "additionalProperties": False,
                    }
                }
            },
        }
    },
)
async def upload_image(
    id: UUID,
    request: Request,
    _admin: Admin,
) -> ImageOut:
    raw_body = await request.body()
    data, alt_text = service.parse_multipart_image(request.headers.get("content-type"), raw_body)
    service.detect_and_validate_raster(data)
    settings: Settings = request.app.state.settings
    async with open_db_session(request) as session:
        return await service.upload_image(session, id, data, alt_text, settings.catalog_storage_dir)


@admin_router.delete("/products/{id}/images/{imageId}", status_code=204)
async def delete_image(
    id: UUID,
    imageId: UUID,
    request: Request,
    _admin: Admin,
) -> None:
    settings: Settings = request.app.state.settings
    async with open_db_session(request) as session:
        await service.delete_image(session, id, imageId, settings.catalog_storage_dir)


# ─────────────────────────────────────────────────────────────────────────────
# Internal API (called by other services; never exposed on public gateway)
# ─────────────────────────────────────────────────────────────────────────────

internal_router = APIRouter(prefix="/internal", tags=["Catalog Internal"])


@internal_router.post("/products/batch", response_model=InternalBatch)
async def batch_products(
    body: InternalBatchRequest,
    request: Request,
    _service: InternalAuth,
) -> InternalBatch:
    async with open_db_session(request) as session:
        return await service.batch_lookup(session, body.product_ids)
