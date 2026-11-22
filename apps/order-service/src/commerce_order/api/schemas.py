"""Order DTOs implementing the public camelCase/string-money contract."""

from collections.abc import Iterable
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from commerce_backend_common.schemas import ApiModel, MoneyAmount, UtcDatetime
from commerce_order.domain.enums import (
    OrderAction,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    WorkflowPhase,
    WorkflowState,
)
from commerce_order.domain.money import (
    MAX_ORDER_ITEMS,
    MAX_QUANTITY,
    PG_BIGINT_MAX,
    calculate_totals,
    line_total,
    parse_money_string,
    validate_amount,
)

Quantity = Annotated[int, Field(strict=True, ge=1, le=MAX_QUANTITY)]
NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]
ShortNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


def _response_money(value: object) -> int:
    if isinstance(value, str):
        return parse_money_string(value)
    if type(value) is int:
        return validate_amount(value)
    raise ValueError("Money must be an integer internally or an ASCII integer string on the wire")


_MONEY_SCHEMA = {"type": "string", "pattern": "^[0-9]+$"}
InputMoney = Annotated[
    MoneyAmount,
    BeforeValidator(parse_money_string),
    Field(le=PG_BIGINT_MAX),
    WithJsonSchema(_MONEY_SCHEMA),
]
OutputMoney = Annotated[
    MoneyAmount,
    BeforeValidator(_response_money),
    Field(le=PG_BIGINT_MAX),
    WithJsonSchema(_MONEY_SCHEMA),
]


class RequestModel(ApiModel):
    # HTTP input uses the published aliases only; internal DTOs may use Python names.
    model_config = ConfigDict(populate_by_name=False, validate_by_name=False)


def _unique_products(product_ids: Iterable[UUID]) -> None:
    seen: set[UUID] = set()
    for product_id in product_ids:
        if product_id in seen:
            raise ValueError("Duplicate products are not allowed")
        seen.add(product_id)


class CartItem(RequestModel):
    product_id: UUID
    quantity: Quantity


class QuoteInput(RequestModel):
    items: list[CartItem] = Field(min_length=1, max_length=MAX_ORDER_ITEMS)

    @model_validator(mode="after")
    def unique_items(self) -> Self:
        _unique_products(item.product_id for item in self.items)
        return self


class ConfirmedItem(CartItem):
    expected_unit_price_amount: InputMoney
    expected_catalog_version: NonnegativeInt


class Recipient(RequestModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    phone: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\+?[0-9]{8,15}$")]
    address: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)
    ]


class CreateOrder(RequestModel):
    items: list[ConfirmedItem] = Field(min_length=1, max_length=MAX_ORDER_ITEMS)
    expected_shipping_fee_amount: InputMoney
    recipient: Recipient
    payment_method: PaymentMethod
    note: ShortNote = ""

    @model_validator(mode="after")
    def unique_items(self) -> Self:
        _unique_products(item.product_id for item in self.items)
        return self


class QuoteItem(ApiModel):
    product_id: UUID
    sku: str
    name: str
    quantity: Quantity
    unit_price_amount: OutputMoney
    line_total_amount: OutputMoney
    catalog_version: NonnegativeInt

    @model_validator(mode="after")
    def correct_line_total(self) -> Self:
        if self.line_total_amount != line_total(self.unit_price_amount, self.quantity):
            raise ValueError("Line total does not match unit price times quantity")
        return self


class PricedSnapshot(ApiModel):
    items: list[QuoteItem]
    subtotal_amount: OutputMoney
    shipping_fee_amount: OutputMoney
    total_amount: OutputMoney
    currency: Literal["VND"]

    @model_validator(mode="after")
    def correct_totals(self) -> Self:
        _unique_products(item.product_id for item in self.items)
        if len({item.sku for item in self.items}) != len(self.items):
            raise ValueError("Duplicate SKUs are not allowed")
        totals = calculate_totals(
            ((item.unit_price_amount, item.quantity) for item in self.items),
            self.shipping_fee_amount,
        )
        if (
            self.subtotal_amount != totals.subtotal_amount
            or self.total_amount != totals.total_amount
        ):
            raise ValueError("Snapshot amounts do not match items and shipping fee")
        return self


class Quote(PricedSnapshot):
    quoted_at: UtcDatetime


class OrderAccepted(ApiModel):
    order_id: UUID
    order_number: str
    status: OrderStatus


class ActionResult(ApiModel):
    order_id: UUID
    status: OrderStatus
    workflow_state: WorkflowState


class History(ApiModel):
    from_status: OrderStatus | None
    to_status: OrderStatus
    reason: str | None
    created_at: UtcDatetime


class WorkflowView(ApiModel):
    phase: WorkflowPhase
    state: WorkflowState
    requires_attention: StrictBool


class Order(PricedSnapshot):
    id: UUID
    order_number: str
    customer_id: UUID
    status: OrderStatus
    payment_id: UUID | None
    payment_status: PaymentStatus | None
    payment_method: PaymentMethod
    recipient: Recipient
    note: str | None
    created_at: UtcDatetime
    workflow: WorkflowView
    history: list[History]
    allowed_actions: list[OrderAction]


class OrderSummary(ApiModel):
    id: UUID
    order_number: str
    status: OrderStatus
    payment_status: PaymentStatus | None
    total_amount: OutputMoney
    currency: Literal["VND"]
    created_at: UtcDatetime


class OrderPage(ApiModel):
    items: list[OrderSummary]
    page: Annotated[int, Field(strict=True, ge=1)]
    page_size: Annotated[int, Field(strict=True, ge=1, le=100)]
    total: NonnegativeInt

    @model_validator(mode="after")
    def bounded_page(self) -> Self:
        if len(self.items) > self.page_size or len(self.items) > self.total:
            raise ValueError("Page items exceed page size or total")
        return self


class Reason(RequestModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class Complete(RequestModel):
    delivered: Literal[True]
    cod_collected: StrictBool = False

    @field_validator("delivered", mode="before")
    @classmethod
    def confirmed_delivery(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Delivery must be explicitly confirmed with boolean true")
        return value

    def validate_for_payment_method(self, method: PaymentMethod) -> None:
        """Completion validates against the stored payment method, never a client field."""
        if method == PaymentMethod.COD and not self.cod_collected:
            raise ValueError("COD completion requires explicit collection confirmation")
