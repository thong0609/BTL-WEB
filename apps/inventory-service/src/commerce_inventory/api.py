"""ADMIN endpoints for warehouse management."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from commerce_backend_common.database import Database
from commerce_backend_common.errors import ServiceError
from commerce_inventory import service
from commerce_inventory.schemas import Movement, Page, Stock, StockAdjustment, StockCreate
from commerce_inventory.upstreams import CatalogClient, Principal, get_catalog, require_admin

router = APIRouter(prefix="/api/v1/admin/inventory", tags=["Inventory"])
Admin = Annotated[Principal, Depends(require_admin)]
PageNumber = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(alias="pageSize", ge=1, le=100)]


def idempotency_key(
    value: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> str:
    if not value.strip():
        raise ServiceError(400, "VALIDATION_ERROR", "Idempotency-Key must not be blank")
    return value


async def inventory_session(request: Request, admin: Admin) -> AsyncIterator[AsyncSession]:
    # Authenticate before exposing DB configuration or acquiring a connection.
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


Session = Annotated[AsyncSession, Depends(inventory_session)]
Key = Annotated[str, Depends(idempotency_key)]


@router.get("", response_model=Page[Stock])
async def get_stock(
    session: Session,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    low_stock: Annotated[bool | None, Query(alias="lowStock")] = None,
) -> Page[Stock]:
    return await service.list_stock(session, page, page_size, low_stock)


@router.post("/items", response_model=Stock, status_code=201)
async def create_stock(
    body: StockCreate,
    session: Session,
    admin: Admin,
    key: Key,
    catalog: Annotated[CatalogClient, Depends(get_catalog)],
) -> Stock:
    return await service.initialize_stock(session, catalog, admin.id, key, body)


@router.post("/adjustments", response_model=Stock)
async def adjust_stock(
    body: StockAdjustment,
    session: Session,
    admin: Admin,
    key: Key,
) -> Stock:
    return await service.adjust_stock(session, admin.id, key, body)


@router.get("/{productId}/movements", response_model=Page[Movement])
async def get_movements(
    productId: UUID,
    session: Session,
    page: PageNumber = 1,
    page_size: PageSize = 20,
) -> Page[Movement]:
    return await service.list_movements(session, productId, page, page_size)
