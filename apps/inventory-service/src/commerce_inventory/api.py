"""ADMIN endpoints for warehouse management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from commerce_inventory import service
from commerce_inventory.dependencies import Admin, AdminSession, Key, get_catalog
from commerce_inventory.schemas import Movement, Page, Stock, StockAdjustment, StockCreate
from commerce_inventory.upstreams import CatalogClient

router = APIRouter(prefix="/api/v1/admin/inventory", tags=["Inventory"])
PageNumber = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(alias="pageSize", ge=1, le=100)]


@router.get("", response_model=Page[Stock])
async def get_stock(
    session: AdminSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    low_stock: Annotated[bool | None, Query(alias="lowStock")] = None,
) -> Page[Stock]:
    return await service.list_stock(session, page, page_size, low_stock)


@router.post("/items", response_model=Stock, status_code=201)
async def create_stock(
    body: StockCreate,
    session: AdminSession,
    admin: Admin,
    key: Key,
    catalog: Annotated[CatalogClient, Depends(get_catalog)],
) -> Stock:
    return await service.initialize_stock(session, catalog, admin.id, key, body)


@router.post("/adjustments", response_model=Stock)
async def adjust_stock(
    body: StockAdjustment,
    session: AdminSession,
    admin: Admin,
    key: Key,
) -> Stock:
    return await service.adjust_stock(session, admin.id, key, body)


@router.get("/{productId}/movements", response_model=Page[Movement])
async def get_movements(
    productId: UUID,
    session: AdminSession,
    page: PageNumber = 1,
    page_size: PageSize = 20,
) -> Page[Movement]:
    return await service.list_movements(session, productId, page, page_size)
