"""Catalog request/response schemas (camelCase on the wire via ApiModel)."""

import re
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BeforeValidator,
    Field,
    PlainSerializer,
    StrictBool,
    field_validator,
    model_validator,
)

from commerce_backend_common.schemas import ApiModel, MoneyAmount

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PRICE_STR_RE = re.compile(r"^[0-9]+$")
MAX_INTEGER = 2_147_483_647
MAX_BIGINT = 9_223_372_036_854_775_807

NonnegativeInt = Annotated[int, Field(strict=True, ge=0, le=MAX_INTEGER)]
ProductStatus = Literal["DRAFT", "ACTIVE", "DISCONTINUED"]
AvailabilityStatus = Literal["IN_STOCK", "OUT_OF_STOCK", "UNKNOWN"]
SortOrder = Literal["NEWEST", "PRICE_ASC", "PRICE_DESC"]


def _parse_price_amount(value: Any) -> int:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("Price amount must be a non-negative integer or digit string")
    if isinstance(value, str):
        if not PRICE_STR_RE.fullmatch(value):
            raise ValueError("Price amount must be a non-negative integer string")
        parsed = int(value)
    elif isinstance(value, int):
        parsed = value
    else:
        raise ValueError("Price amount must be a non-negative integer or digit string")
    if parsed < 0 or parsed > MAX_BIGINT:
        raise ValueError("Price amount is out of valid VND bounds")
    return parsed


PriceInput = Annotated[
    int,
    BeforeValidator(_parse_price_amount),
    Field(ge=0, le=MAX_BIGINT),
    PlainSerializer(str, return_type=str, when_used="json"),
]


def _validate_slug(value: str) -> str:
    if not SLUG_RE.fullmatch(value):
        raise ValueError("Slug must be lowercase alphanumeric with hyphens only")
    return value


def _validate_specifications(specs: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, val in specs.items():
        k = key.strip()
        if not k or len(k) > 100:
            raise ValueError("Specification keys must be 1..100 non-blank characters")
        if len(val) > 500:
            raise ValueError("Specification values must be at most 500 characters")
        cleaned[k] = val
    return cleaned


class Page[T](ApiModel):
    items: list[T]
    page: int
    page_size: int
    total: int


class ImageOut(ApiModel):
    id: UUID
    url: str
    alt_text: str | None
    sort_order: int


class CategoryOut(ApiModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    is_visible: bool


class CategoryInput(ApiModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    slug: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str, Field(max_length=2000)] | None = None
    is_visible: StrictBool = True

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Name must not be blank")
        return trimmed

    @field_validator("slug")
    @classmethod
    def slug_format(cls, value: str) -> str:
        return _validate_slug(value)


class CategoryPatch(ApiModel):
    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    slug: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    description: Annotated[str, Field(max_length=2000)] | None = None
    is_visible: StrictBool | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Name must not be blank")
        return trimmed

    @field_validator("slug")
    @classmethod
    def slug_format(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_slug(value)

    @model_validator(mode="after")
    def at_least_one(self) -> "CategoryPatch":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for non_null_field in ("name", "slug", "is_visible"):
            if non_null_field in self.model_fields_set and getattr(self, non_null_field) is None:
                raise ValueError(f"{non_null_field} must not be null")
        return self


class ProductOut(ApiModel):
    id: UUID
    sku: str
    slug: str
    name: str
    category_id: UUID
    description: str
    specifications: dict[str, str]
    price_amount: MoneyAmount
    currency: Literal["VND"]
    status: ProductStatus
    version: int
    images: list[ImageOut]
    availability: AvailabilityStatus


class ProductInput(ApiModel):
    sku: Annotated[str, Field(min_length=1, max_length=64)]
    slug: Annotated[str, Field(min_length=1, max_length=180)]
    name: Annotated[str, Field(min_length=1, max_length=200)]
    category_id: UUID
    description: Annotated[str, Field(max_length=10000)] = ""
    specifications: dict[str, str] = Field(default_factory=dict)
    price_amount: PriceInput
    currency: Literal["VND"] = "VND"
    status: ProductStatus = "DRAFT"

    @field_validator("sku")
    @classmethod
    def sku_not_blank(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("SKU must not be blank")
        return trimmed

    @field_validator("slug")
    @classmethod
    def slug_format(cls, value: str) -> str:
        return _validate_slug(value)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Name must not be blank")
        return trimmed

    @field_validator("specifications")
    @classmethod
    def valid_specs(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_specifications(value)


class ProductPatch(ApiModel):
    slug: Annotated[str, Field(min_length=1, max_length=180)] | None = None
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    category_id: UUID | None = None
    description: Annotated[str, Field(max_length=10000)] | None = None
    specifications: dict[str, str] | None = None
    price_amount: PriceInput | None = None
    currency: Literal["VND"] | None = None
    status: ProductStatus | None = None
    expected_version: NonnegativeInt
    image_ids: Annotated[list[UUID], Field(max_length=5)] | None = None

    @field_validator("slug")
    @classmethod
    def slug_format(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_slug(value)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Name must not be blank")
        return trimmed

    @field_validator("specifications")
    @classmethod
    def valid_specs(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        return _validate_specifications(value)

    @field_validator("image_ids")
    @classmethod
    def unique_image_ids(cls, value: list[UUID] | None) -> list[UUID] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("imageIds must not contain duplicates")
        return value

    @model_validator(mode="after")
    def at_least_one_besides_version(self) -> "ProductPatch":
        changed = self.model_fields_set - {"expected_version"}
        if not changed:
            raise ValueError("At least one field besides expectedVersion must be provided")
        for field_name in changed:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} must not be null")
        return self


class InternalBatchRequest(ApiModel):
    product_ids: Annotated[list[UUID], Field(min_length=1, max_length=50)]

    @field_validator("product_ids")
    @classmethod
    def unique_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("productIds must contain unique items")
        return value


class InternalProduct(ApiModel):
    id: UUID
    sku: str
    name: str
    status: ProductStatus
    price_amount: MoneyAmount
    version: int


class InternalBatch(ApiModel):
    items: list[InternalProduct]
