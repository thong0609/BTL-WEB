"""Read-only adapters for proposed Inventory/Payment reconciliation contracts."""

from typing import Annotated, Literal, Self
from uuid import UUID

import httpx
from pydantic import ConfigDict, Field, SecretStr, model_validator

from commerce_backend_common.messaging import MessageEnvelope
from commerce_backend_common.schemas import ApiModel
from commerce_order.api.schemas import InputMoney
from commerce_order.domain.enums import PaymentMethod, PaymentStatus
from commerce_order.messaging.schemas import EVENTS, Event, Payment, decode_event

Version = Annotated[int, Field(strict=True, ge=0, le=2147483647)]


class RecoveryUnavailable(RuntimeError):
    pass


class Snapshot(ApiModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=False, validate_by_name=False)
    order_id: UUID
    events: list[MessageEnvelope] = Field(max_length=100)


class InventorySnapshot(Snapshot):
    reservation_id: UUID | None
    status: Literal["RESERVED", "RELEASED", "COMMITTED", "NOT_FOUND"]
    version: Version

    @model_validator(mode="after")
    def reference(self) -> Self:
        if (self.status == "NOT_FOUND") != (self.reservation_id is None):
            raise ValueError("Reservation reference does not match status")
        return self


class PaymentSnapshot(Snapshot):
    payment_id: UUID | None
    status: PaymentStatus | None
    version: Version | None
    method: PaymentMethod | None
    amount: InputMoney | None
    currency: Literal["VND"] | None
    operation_id: UUID | None
    command_message_id: UUID | None

    @model_validator(mode="after")
    def reference(self) -> Self:
        fields = (
            self.payment_id,
            self.status,
            self.version,
            self.method,
            self.amount,
            self.currency,
        )
        if any(value is None for value in fields) and not all(value is None for value in fields):
            raise ValueError("Payment snapshot reference is incomplete")
        return self


class SnapshotClient[T: Snapshot]:
    def __init__(
        self, http: httpx.AsyncClient, token: SecretStr | None, schema: type[T], path: str
    ) -> None:
        self.http, self.token, self.schema, self.path = http, token, schema, path

    async def get(self, order_id: UUID, correlation_id: UUID) -> T | None:
        if self.token is None:
            raise RecoveryUnavailable("RECOVERY_ACCESS_NOT_CONFIGURED")
        try:
            async with self.http.stream(
                "GET",
                self.path + str(order_id),
                headers={
                    "Authorization": f"Bearer {self.token.get_secret_value()}",
                    "X-Request-Id": str(correlation_id),
                },
            ) as response:
                if response.status_code == 404:
                    return None
                if response.status_code != 200:
                    raise RecoveryUnavailable("RECOVERY_DEPENDENCY_UNAVAILABLE")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > 1048576:
                        raise RecoveryUnavailable("RECOVERY_RESPONSE_TOO_LARGE")
                    content.extend(chunk)
            snapshot = self.schema.model_validate_json(bytes(content))
            if snapshot.order_id != order_id:
                raise RecoveryUnavailable("RECOVERY_ORDER_MISMATCH")
            return snapshot
        except RecoveryUnavailable:
            raise
        except Exception:
            raise RecoveryUnavailable("RECOVERY_RESPONSE_INVALID") from None


def receipts(snapshot: Snapshot) -> list[Event]:
    """Replay original producer messages; never invent a success event or messageId."""
    result = []
    for envelope in snapshot.events:
        definition = EVENTS.get(envelope.message_type)
        if definition is None:
            raise RecoveryUnavailable("RECOVERY_EVENT_UNKNOWN")
        inventory = envelope.message_type.startswith("Stock")
        if inventory != isinstance(snapshot, InventorySnapshot):
            raise RecoveryUnavailable("RECOVERY_SOURCE_MISMATCH")
        event = decode_event(envelope.model_dump_json().encode(), definition[0])
        if event.payload.order_id != snapshot.order_id:
            raise RecoveryUnavailable("RECOVERY_ORDER_MISMATCH")
        if isinstance(snapshot, InventorySnapshot):
            reference = getattr(event.payload, "reservation_id", None)
            if reference is not None and reference != snapshot.reservation_id:
                raise RecoveryUnavailable("RECOVERY_RESERVATION_MISMATCH")
        if isinstance(snapshot, PaymentSnapshot):
            reference = getattr(event.payload, "payment_id", None)
            if reference is not None and reference != snapshot.payment_id:
                raise RecoveryUnavailable("RECOVERY_PAYMENT_MISMATCH")
            version = getattr(event.payload, "payment_version", None)
            if version is not None and snapshot.version is not None and version > snapshot.version:
                raise RecoveryUnavailable("RECOVERY_VERSION_MISMATCH")
            if (
                version is not None
                and version == snapshot.version
                and getattr(event.payload, "payment_status", None) != snapshot.status
            ):
                raise RecoveryUnavailable("RECOVERY_STATUS_MISMATCH")
        result.append(event)
    if isinstance(snapshot, InventorySnapshot) and result:
        known = {
            "StockReserved": "RESERVED",
            "StockReleased": "RELEASED",
            "StockCommitted": "COMMITTED",
            "StockReservationFailed": "NOT_FOUND",
        }
        states = [
            known[event.envelope.message_type]
            for event in result
            if event.envelope.message_type in known
        ]
        if states and states[-1] != snapshot.status:
            raise RecoveryUnavailable("RECOVERY_STATUS_MISMATCH")
    if isinstance(snapshot, PaymentSnapshot) and snapshot.status not in {
        None,
        PaymentStatus.PENDING,
    }:
        known_payments = [event.payload for event in result if isinstance(event.payload, Payment)]
        if (
            not known_payments
            or max(row.payment_version for row in known_payments) != snapshot.version
        ):
            raise RecoveryUnavailable("RECOVERY_TERMINAL_PROOF_MISSING")
    return result
