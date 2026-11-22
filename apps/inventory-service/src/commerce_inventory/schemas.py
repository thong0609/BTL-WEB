"""HTTP request/response schemas for admin, internal and upstream APIs (camelCase on the wire)."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from commerce_backend_common.schemas import ApiModel, UtcDatetime

NonnegativeInt = Annotated[int, Field(strict=True, ge=0, le=2_147_483_647)]


class StockCreate(ApiModel):
    product_id: UUID
    low_stock_threshold: NonnegativeInt = 5


class StockAdjustment(ApiModel):
    product_id: UUID
    delta: Annotated[int, Field(strict=True, ge=-2_147_483_648, le=2_147_483_647)]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    expected_version: NonnegativeInt

    @field_validator("delta")
    @classmethod
    def nonzero_delta(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Delta must be nonzero")
        return value

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Reason must not be blank")
        return value


class Stock(ApiModel):
    product_id: UUID
    on_hand_quantity: int
    reserved_quantity: int
    available_quantity: int
    low_stock_threshold: int
    version: int


class Movement(ApiModel):
    id: UUID
    operation_id: UUID
    product_id: UUID
    movement_type: str
    on_hand_delta: int
    reserved_delta: int
    on_hand_after: int
    reserved_after: int
    reason: str
    created_at: UtcDatetime


class Page[T](ApiModel):
    items: list[T]
    page: int
    page_size: int
    total: int


class AvailabilityRequest(ApiModel):
    product_ids: list[UUID] = Field(min_length=1, max_length=50)

    @field_validator("product_ids")
    @classmethod
    def unique_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Duplicate products")
        return value


class Availability(ApiModel):
    product_id: UUID
    stocked: bool
    available_quantity: int


class AvailabilityResponse(ApiModel):
    items: list[Availability]


class ReservationLine(ApiModel):
    product_id: UUID
    quantity: int


class ReservationView(ApiModel):
    reservation_id: UUID
    order_id: UUID
    status: Literal["RESERVED", "RELEASED", "COMMITTED"]
    version: int
    items: list[ReservationLine]
    created_at: UtcDatetime
    updated_at: UtcDatetime
    released_at: UtcDatetime | None
    committed_at: UtcDatetime | None


class Principal(BaseModel):
    id: UUID
    role: Literal["ADMIN", "CUSTOMER"]
    status: Literal["ACTIVE", "DISABLED"]


class CatalogProduct(BaseModel):
    id: UUID


class CatalogBatch(BaseModel):
    items: list[CatalogProduct]
