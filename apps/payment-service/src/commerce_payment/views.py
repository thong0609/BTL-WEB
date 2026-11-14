"""HTTP response models matching docs/contracts/openapi.yaml."""

from typing import Literal
from uuid import UUID

from commerce_backend_common.schemas import ApiModel, MoneyAmount


class RefundView(ApiModel):
    id: UUID
    status: Literal["PENDING", "SUCCEEDED", "NEEDS_ATTENTION"]
    amount: MoneyAmount


class PaymentView(ApiModel):
    id: UUID
    order_id: UUID
    method: Literal["COD", "SIMULATED"]
    amount: MoneyAmount
    currency: Literal["VND"]
    status: Literal[
        "PENDING",
        "AWAITING_COLLECTION",
        "SUCCEEDED",
        "FAILED",
        "REFUND_PENDING",
        "REFUNDED",
        "CANCELLED",
    ]
    version: int
    refund: RefundView | None


class DemoScenario(ApiModel):
    payment_scenario: Literal["SUCCESS", "FAILURE", "DELAYED_SUCCESS", "DELAYED_FAILURE"]
    refund_scenario: Literal["SUCCESS", "DELAYED_SUCCESS", "FAIL_UNTIL_RETRY"]
    delay_seconds: int
