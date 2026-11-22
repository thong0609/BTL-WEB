"""Version-one message payloads from MESSAGES.md; compatible extra fields are ignored."""

import hashlib
import json
from dataclasses import dataclass
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, StrictBool, StringConstraints, model_validator

from commerce_backend_common.messaging import MessageEnvelope, parse_envelope
from commerce_backend_common.schemas import ApiModel
from commerce_order.api.schemas import InputMoney, Quantity
from commerce_order.domain.enums import PaymentMethod, PaymentStatus

Code = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]
Version = Annotated[int, Field(strict=True, ge=0, le=2147483647)]


class MessageInvalid(ValueError):
    """Safe reason codes only. Raw payloads and exception text must not reach logs."""


class EventRetryable(RuntimeError):
    pass


class Payload(ApiModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=False, validate_by_name=False)
    order_id: UUID
    operation_id: UUID


class Item(ApiModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=False, validate_by_name=False)
    product_id: UUID
    quantity: Quantity


class StockItems(Payload):
    items: list[Item] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_items(self) -> Self:
        if len({item.product_id for item in self.items}) != len(self.items):
            raise ValueError("Duplicate product IDs")
        return self


class StockReserved(StockItems):
    reservation_id: UUID


class Shortage(ApiModel):
    model_config = ConfigDict(extra="ignore")
    product_id: UUID
    requested: Quantity
    available: Annotated[int, Field(strict=True, ge=0)]


class StockReservationFailed(Payload):
    code: Code
    shortages: list[Shortage] = Field(max_length=50)


class Reservation(Payload):
    reservation_id: UUID


class ReservationFailure(Reservation):
    code: Code


class Payment(Payload):
    payment_id: UUID
    payment_version: Version
    payment_status: PaymentStatus


class PaymentAmount(Payment):
    amount: InputMoney
    currency: Literal["VND"]


class PaymentInitialized(PaymentAmount):
    method: Literal["COD"]
    payment_status: Literal[PaymentStatus.AWAITING_COLLECTION]


class PaymentSucceeded(PaymentAmount):
    method: Literal["SIMULATED"]
    payment_status: Literal[PaymentStatus.SUCCEEDED]


class PaymentFailed(PaymentAmount):
    code: Code
    payment_status: Literal[PaymentStatus.FAILED]


class CodCollected(PaymentAmount):
    collected_by: UUID
    payment_status: Literal[PaymentStatus.SUCCEEDED]


class CodPaymentCancelled(PaymentAmount):
    payment_status: Literal[PaymentStatus.CANCELLED]


class PaymentRefunded(PaymentAmount):
    refund_id: UUID
    payment_status: Literal[PaymentStatus.REFUNDED]


class PaymentRefundFailed(Payment):
    refund_id: UUID
    code: Code
    retryable: StrictBool
    payment_status: Literal[PaymentStatus.REFUND_PENDING]


class PaymentCommandRejected(Payload):
    rejected_type: Literal[
        "InitializeCodPayment",
        "ProcessPayment",
        "RecordCodCollection",
        "CancelCodPayment",
        "RefundPayment",
    ]
    code: Code
    payment_id: UUID | None
    payment_version: Version | None
    payment_status: PaymentStatus | None

    @model_validator(mode="after")
    def complete_payment_reference(self) -> Self:
        fields = (self.payment_id, self.payment_version, self.payment_status)
        if any(value is None for value in fields) and not all(value is None for value in fields):
            raise ValueError("Payment reference must be complete or entirely null")
        return self


class ReasonReservation(Reservation):
    reason: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1000)]


class InitiatePayment(Payload):
    customer_id: UUID
    amount: InputMoney
    currency: Literal["VND"]


class PaymentReference(Payload):
    payment_id: UUID


class CollectCod(PaymentReference):
    collected_by: UUID


class CancelCod(PaymentReference):
    reason: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1000)]


class Refund(CancelCod):
    amount: InputMoney
    currency: Literal["VND"]


# type -> (routing key, payload schema). Both success and failure routes are explicit.
EVENTS: dict[str, tuple[str, type[Payload]]] = {
    "StockReserved": ("inventory.stock-reserved", StockReserved),
    "StockReservationFailed": ("inventory.stock-reservation-failed", StockReservationFailed),
    "StockReleased": ("inventory.stock-released", Reservation),
    "StockReleaseFailed": ("inventory.stock-release-failed", ReservationFailure),
    "StockCommitted": ("inventory.stock-committed", Reservation),
    "StockCommitFailed": ("inventory.stock-commit-failed", ReservationFailure),
    "PaymentInitialized": ("payment.initialized", PaymentInitialized),
    "PaymentSucceeded": ("payment.succeeded", PaymentSucceeded),
    "PaymentFailed": ("payment.failed", PaymentFailed),
    "CodCollected": ("payment.cod-collected", CodCollected),
    "CodPaymentCancelled": ("payment.cod-cancelled", CodPaymentCancelled),
    "PaymentRefunded": ("payment.refunded", PaymentRefunded),
    "PaymentRefundFailed": ("payment.refund-failed", PaymentRefundFailed),
    "PaymentCommandRejected": ("payment.command-rejected", PaymentCommandRejected),
}
COMMANDS: dict[str, tuple[str, type[Payload]]] = {
    "ReserveStock": ("inventory.reserve", StockItems),
    "ReleaseStock": ("inventory.release", ReasonReservation),
    "CommitStock": ("inventory.commit", Reservation),
    "InitializeCodPayment": ("payment.initialize-cod", InitiatePayment),
    "ProcessPayment": ("payment.process", InitiatePayment),
    "RecordCodCollection": ("payment.collect-cod", CollectCod),
    "CancelCodPayment": ("payment.cancel-cod", CancelCod),
    "RefundPayment": ("payment.refund", Refund),
}


@dataclass(frozen=True)
class Event:
    envelope: MessageEnvelope
    payload: Payload
    digest: str


@dataclass(frozen=True)
class PaymentEvidence:
    """Exact original result confirmed by an authenticated recovery snapshot."""

    message_id: UUID
    order_id: UUID
    payment_id: UUID
    version: int
    status: PaymentStatus
    method: PaymentMethod
    amount: int
    currency: str


def decode_event(body: bytes, routing_key: str, max_bytes: int = 262144) -> Event:
    try:
        envelope = parse_envelope(body, max_bytes)
        definition = EVENTS.get(envelope.message_type)
        if definition is None or definition[0] != routing_key:
            raise MessageInvalid("EVENT_ROUTE_INVALID")
        payload = definition[1].model_validate(envelope.payload)
        canonical = json.dumps(
            envelope.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        return Event(envelope, payload, hashlib.sha256(canonical.encode()).hexdigest())
    except MessageInvalid:
        raise
    except Exception:
        raise MessageInvalid("EVENT_SCHEMA_INVALID") from None
