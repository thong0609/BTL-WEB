"""Payment command contracts. Amounts on the wire are integer VND strings."""

import hashlib
import json
from collections.abc import Mapping
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BeforeValidator, Field, ValidationError, field_validator

from commerce_backend_common.messaging import MessageEnvelope
from commerce_backend_common.schemas import ApiModel


class PaymentMessageError(Exception):
    """Technical message failure. Callers must not record this as PaymentFailed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def parse_vnd(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, str) or not value.isdecimal():
        raise ValueError("Amount must be a non-negative integer string")
    if len(value) > 18:
        raise ValueError("Amount is too large")
    return int(value)


VndAmount = Annotated[int, BeforeValidator(parse_vnd)]


def _required_reason(value: str) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > 1000:
        raise ValueError("Reason must be 1..1000 characters")
    return stripped


class InitializeCodPayment(ApiModel):
    order_id: UUID
    operation_id: UUID
    customer_id: UUID
    amount: VndAmount
    currency: Literal["VND"]


class ProcessPayment(ApiModel):
    order_id: UUID
    operation_id: UUID
    customer_id: UUID
    amount: VndAmount
    currency: Literal["VND"]


class RecordCodCollection(ApiModel):
    order_id: UUID
    operation_id: UUID
    payment_id: UUID
    collected_by: UUID


class CancelCodPayment(ApiModel):
    order_id: UUID
    operation_id: UUID
    payment_id: UUID
    reason: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return _required_reason(value)


class RefundPayment(ApiModel):
    order_id: UUID
    operation_id: UUID
    payment_id: UUID
    amount: VndAmount
    currency: Literal["VND"]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return _required_reason(value)


Command = (
    InitializeCodPayment | ProcessPayment | RecordCodCollection | CancelCodPayment | RefundPayment
)

_COMMANDS: dict[str, type[Command]] = {
    "InitializeCodPayment": InitializeCodPayment,
    "ProcessPayment": ProcessPayment,
    "RecordCodCollection": RecordCodCollection,
    "CancelCodPayment": CancelCodPayment,
    "RefundPayment": RefundPayment,
}


def parse_command(envelope: MessageEnvelope) -> Command:
    model = _COMMANDS.get(envelope.message_type)
    if model is None:
        raise PaymentMessageError("INVALID_MESSAGE")
    try:
        return model.model_validate(envelope.payload)
    except ValidationError:
        raise PaymentMessageError("INVALID_MESSAGE") from None


def command_hash(command: Command) -> str:
    body = command.model_dump(mode="json", by_alias=True)
    body["type"] = type(command).__name__
    if "amount" in body:
        body["amount"] = str(body["amount"])
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def payload_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
