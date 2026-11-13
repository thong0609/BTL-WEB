"""INV-01 public request/response schemas (camelCase on the wire)."""

from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator

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
