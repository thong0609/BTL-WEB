"""Inventory command contracts and atomic, replay-safe stock transitions."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from commerce_backend_common.messaging import MessageEnvelope
from commerce_backend_common.schemas import ApiModel
from commerce_inventory.models import (
    InventoryOperation,
    OutboxMessage,
    ProcessedMessage,
    Reservation,
    ReservationItem,
    StockItem,
    StockMovement,
)
from commerce_inventory.service import MAX_INTEGER

CONSUMER = "inventory.commands.v1"
ROUTES = {
    "ReserveStock": "inventory.reserve",
    "ReleaseStock": "inventory.release",
    "CommitStock": "inventory.commit",
}
EVENT_ROUTES = {
    "StockReserved": "inventory.stock-reserved",
    "StockReservationFailed": "inventory.stock-reservation-failed",
    "StockReleased": "inventory.stock-released",
    "StockReleaseFailed": "inventory.stock-release-failed",
    "StockCommitted": "inventory.stock-committed",
    "StockCommitFailed": "inventory.stock-commit-failed",
}


class InvalidCommand(ValueError):
    """Permanent transport/schema error: reject to DLQ without a fabricated event."""


class CommandModel(ApiModel):
    model_config = ConfigDict(extra="ignore")


class Line(CommandModel):
    product_id: UUID
    quantity: int = Field(strict=True, gt=0, le=MAX_INTEGER)


class Command(CommandModel):
    order_id: UUID
    operation_id: UUID


class Reserve(Command):
    items: list[Line] = Field(min_length=1, max_length=50)

    @field_validator("items")
    @classmethod
    def unique_products(cls, items: list[Line]) -> list[Line]:
        if len({item.product_id for item in items}) != len(items):
            raise ValueError("Duplicate products")
        return sorted(items, key=lambda item: item.product_id)


class Commit(Command):
    reservation_id: UUID


class Release(Commit):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Reason must not be blank")
        return value


def parse_command(envelope: MessageEnvelope, routing_key: str | None = None) -> Command:
    models: dict[str, type[Command]] = {
        "ReserveStock": Reserve,
        "ReleaseStock": Release,
        "CommitStock": Commit,
    }
    model = models.get(envelope.message_type)
    if model is None or (routing_key is not None and ROUTES[envelope.message_type] != routing_key):
        raise InvalidCommand("Unsupported command or routing key")
    return model.model_validate(envelope.payload)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


async def lock(session: AsyncSession, scope: str, identity: UUID) -> None:
    key = int.from_bytes(
        hashlib.sha256(f"{scope}:{identity}".encode()).digest()[:8], "big", signed=True
    )
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def failure(command: Command, code: str) -> dict[str, Any]:
    if isinstance(command, Reserve):
        return {"type": "StockReservationFailed", "code": code, "shortages": []}
    assert isinstance(command, Commit)
    return {
        "type": "StockReleaseFailed" if isinstance(command, Release) else "StockCommitFailed",
        "reservationId": str(command.reservation_id),
        "code": code,
    }


async def stock_rows(session: AsyncSession, ids: list[UUID]) -> dict[UUID, StockItem]:
    rows = (
        await session.scalars(
            select(StockItem)
            .where(StockItem.product_id.in_(ids))
            .order_by(StockItem.product_id)
            .with_for_update()
        )
    ).all()
    return {row.product_id: row for row in rows}


async def reserve(session: AsyncSession, command: Reserve) -> dict[str, Any]:
    current = await session.scalar(
        select(Reservation).where(Reservation.order_id == command.order_id).with_for_update()
    )
    if current is not None:
        lines = (
            await session.scalars(
                select(ReservationItem)
                .where(ReservationItem.reservation_id == current.id)
                .order_by(ReservationItem.product_id)
            )
        ).all()
        if current.status != "RESERVED" or [(x.product_id, x.quantity) for x in lines] != [
            (x.product_id, x.quantity) for x in command.items
        ]:
            return failure(command, "RESERVATION_STATE_CONFLICT")
        return {
            "type": "StockReserved",
            "reservationId": str(current.id),
            "items": [x.model_dump(mode="json") for x in command.items],
        }
    rows = await stock_rows(session, [line.product_id for line in command.items])
    shortages = []
    missing = False
    for line in command.items:
        item = rows.get(line.product_id)
        available = item.available_quantity if item else 0
        if item is None or available < line.quantity:
            missing |= item is None
            shortages.append(
                {
                    "productId": str(line.product_id),
                    "requested": line.quantity,
                    "available": available,
                }
            )
    if shortages:
        return {
            **failure(command, "PRODUCT_NOT_STOCKED" if missing else "INSUFFICIENT_STOCK"),
            "shortages": shortages,
        }
    if any(item.version == MAX_INTEGER for item in rows.values()):
        return failure(command, "STOCK_LIMIT_EXCEEDED")
    reservation = Reservation(id=uuid4(), order_id=command.order_id, status="RESERVED")
    session.add(reservation)
    await session.flush()
    for line in command.items:
        item = rows[line.product_id]
        item.reserved_quantity += line.quantity
        item.version += 1
        session.add(
            ReservationItem(
                reservation_id=reservation.id, product_id=line.product_id, quantity=line.quantity
            )
        )
        movement(
            session,
            command,
            reservation.id,
            item,
            "RESERVE",
            0,
            line.quantity,
            "Order stock reservation",
        )
    return {
        "type": "StockReserved",
        "reservationId": str(reservation.id),
        "items": [line.model_dump(mode="json") for line in command.items],
    }


def movement(
    session: AsyncSession,
    command: Command,
    reservation_id: UUID,
    item: StockItem,
    kind: str,
    on_hand: int,
    reserved: int,
    reason: str,
) -> None:
    session.add(
        StockMovement(
            operation_id=command.operation_id,
            product_id=item.product_id,
            reservation_id=reservation_id,
            movement_type=kind,
            on_hand_delta=on_hand,
            reserved_delta=reserved,
            on_hand_after=item.on_hand_quantity,
            reserved_after=item.reserved_quantity,
            reason=reason,
            actor_type="SYSTEM",
        )
    )


async def finish(session: AsyncSession, command: Commit) -> dict[str, Any]:
    reservation = await session.scalar(
        select(Reservation).where(Reservation.id == command.reservation_id).with_for_update()
    )
    if reservation is None or reservation.order_id != command.order_id:
        return failure(command, "RESERVATION_NOT_FOUND")
    releasing = isinstance(command, Release)
    target = "RELEASED" if releasing else "COMMITTED"
    result = {
        "type": "StockReleased" if releasing else "StockCommitted",
        "reservationId": str(reservation.id),
    }
    if reservation.status == target:
        return result
    if reservation.status != "RESERVED":
        return failure(command, "RESERVATION_STATE_CONFLICT")
    lines = (
        await session.scalars(
            select(ReservationItem)
            .where(ReservationItem.reservation_id == reservation.id)
            .order_by(ReservationItem.product_id)
        )
    ).all()
    rows = await stock_rows(session, [line.product_id for line in lines])
    if reservation.version == MAX_INTEGER or any(x.version == MAX_INTEGER for x in rows.values()):
        return failure(command, "STOCK_LIMIT_EXCEEDED")
    # Broken counters are a technical integrity fault; rollback and require investigation.
    if not lines or any(rows[line.product_id].reserved_quantity < line.quantity for line in lines):
        raise RuntimeError("Reservation counters are inconsistent")
    for line in lines:
        item = rows[line.product_id]
        item.reserved_quantity -= line.quantity
        delta = 0 if releasing else -line.quantity
        item.on_hand_quantity += delta
        item.version += 1
        movement(
            session,
            command,
            reservation.id,
            item,
            "RELEASE" if releasing else "COMMIT",
            delta,
            -line.quantity,
            command.reason if isinstance(command, Release) else "Order stock dispatch",
        )
    reservation.status = target
    reservation.version += 1
    if releasing:
        reservation.released_at = datetime.now(UTC)
    else:
        reservation.committed_at = datetime.now(UTC)
    return result


async def process_command(
    session: AsyncSession, envelope: MessageEnvelope, routing_key: str | None = None
) -> dict[str, Any] | None:
    """Return committed result; None means an identical message was already committed."""
    command = parse_command(envelope, routing_key)
    message_hash = digest(envelope.model_dump(mode="json"))
    request_hash = digest(
        {"type": envelope.message_type, "payload": command.model_dump(mode="json")}
    )
    kind = {"ReserveStock": "RESERVE", "ReleaseStock": "RELEASE", "CommitStock": "COMMIT"}[
        envelope.message_type
    ]
    async with session.begin():
        await lock(session, "message", envelope.message_id)
        inbox = await session.get(ProcessedMessage, (CONSUMER, envelope.message_id))
        if inbox is not None:
            if inbox.payload_hash != message_hash:
                raise InvalidCommand("Message identity was reused with different contents")
            return None
        # Share the operation lock with INV-01 so cross-scope UUID reuse is also safe.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": int.from_bytes(command.operation_id.bytes[:8], "big", signed=True)},
        )
        operation = await session.get(InventoryOperation, command.operation_id)
        if operation is not None:
            if operation.request_hash != request_hash or operation.operation_type != kind:
                result = failure(command, "OPERATION_CONFLICT")
            else:
                result = operation.result_payload
        else:
            await lock(session, "order", command.order_id)
            # Insert operation first for movement FKs; still invisible until full commit.
            operation = InventoryOperation(
                operation_id=command.operation_id,
                order_id=command.order_id,
                operation_type=kind,
                request_hash=request_hash,
                result_status="SUCCEEDED",
                result_payload={},
            )
            session.add(operation)
            await session.flush()
            if isinstance(command, Reserve):
                result = await reserve(session, command)
            else:
                assert isinstance(command, Commit)
                result = await finish(session, command)
            operation.result_payload = result
            operation.result_status = "REJECTED" if "code" in result else "SUCCEEDED"
            operation.error_code = result.get("code")
        payload = {key: value for key, value in result.items() if key != "type"}
        payload.update(orderId=str(command.order_id), operationId=str(command.operation_id))
        session.add(
            OutboxMessage(
                message_type=result["type"],
                aggregate_type="RESERVATION" if "reservationId" in result else "ORDER",
                aggregate_id=UUID(result.get("reservationId", str(command.order_id))),
                exchange_name="commerce.events",
                routing_key=EVENT_ROUTES[result["type"]],
                correlation_id=envelope.correlation_id,
                causation_id=envelope.message_id,
                payload=payload,
            )
        )
        session.add(
            ProcessedMessage(
                consumer_name=CONSUMER,
                message_id=envelope.message_id,
                message_type=envelope.message_type,
                message_version=envelope.version,
                payload_hash=message_hash,
                correlation_id=envelope.correlation_id,
            )
        )
    return result
