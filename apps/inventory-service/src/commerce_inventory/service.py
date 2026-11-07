"""INV-01 use cases. The transaction owns counters, operation and audit movement."""

import hashlib
import json
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from commerce_backend_common.errors import ServiceError
from commerce_inventory.models import InventoryOperation, StockItem, StockMovement
from commerce_inventory.schemas import Movement, Page, Stock, StockAdjustment, StockCreate
from commerce_inventory.upstreams import CatalogClient

# Stable namespace: changing it would invalidate existing idempotency keys.
OPERATION_NAMESPACE = UUID("6c33ca89-3f28-44a6-a848-68bc6d4b0747")
MAX_INTEGER = 2_147_483_647


def stock_view(item: StockItem) -> Stock:
    return Stock(
        product_id=item.product_id,
        on_hand_quantity=item.on_hand_quantity,
        reserved_quantity=item.reserved_quantity,
        available_quantity=item.available_quantity,
        low_stock_threshold=item.low_stock_threshold,
        version=item.version,
    )


def operation_identity(
    actor: UUID, scope: str, key: str, body: StockCreate | StockAdjustment
) -> tuple[UUID, str]:
    identity = {"actor": str(actor), "scope": scope, "key": key}
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    request = json.dumps(
        {**identity, "body": body.model_dump(mode="json")},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return uuid5(OPERATION_NAMESPACE, encoded), hashlib.sha256(request.encode()).hexdigest()


def replay(operation: InventoryOperation) -> Stock:
    result = operation.result_payload
    if operation.result_status == "REJECTED":
        raise ServiceError(result["status"], result["code"], result["message"])
    return Stock.model_validate(result["stock"])


async def existing_operation(
    session: AsyncSession, operation_id: UUID, request_hash: str, operation_type: str
) -> InventoryOperation | None:
    # Serializes the same key across processes before lookup/insert. A lock hash
    # collision only serializes unrelated requests; full identity is verified below.
    lock_id = int.from_bytes(operation_id.bytes[:8], "big", signed=True)
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
    operation = await session.get(InventoryOperation, operation_id)
    if operation is not None and (
        operation.request_hash != request_hash or operation.operation_type != operation_type
    ):
        raise ServiceError(409, "IDEMPOTENCY_CONFLICT", "Key was already used for another request")
    return operation


def save_operation(
    session: AsyncSession,
    operation_id: UUID,
    request_hash: str,
    operation_type: str,
    actor: UUID,
    stock: Stock | None = None,
    error: ServiceError | None = None,
) -> InventoryOperation:
    result: dict[str, Any] = {"actorId": str(actor)}
    if error is not None:
        result.update(status=error.status, code=error.code, message=error.public_message)
    elif stock is not None:
        result["stock"] = stock.model_dump(mode="json")
    operation = InventoryOperation(
        operation_id=operation_id,
        operation_type=operation_type,
        request_hash=request_hash,
        result_status="REJECTED" if error else "SUCCEEDED",
        result_payload=result,
        error_code=error.code if error else None,
    )
    session.add(operation)
    return operation


async def initialize_stock(
    session: AsyncSession, catalog: CatalogClient, actor: UUID, key: str, body: StockCreate
) -> Stock:
    operation_id, request_hash = operation_identity(actor, "inventory.initialize", key, body)
    async with session.begin():
        operation = await existing_operation(session, operation_id, request_hash, "INITIALIZE")
        if operation is None:
            # Replays need neither Catalog availability nor another write.
            try:
                await catalog.verify_product(body.product_id)
            except ServiceError as exc:
                if exc.status != 404:
                    raise  # Technical/dependency failures release the key for retry.
                operation = save_operation(
                    session, operation_id, request_hash, "INITIALIZE", actor, error=exc
                )
            else:
                await session.execute(
                    insert(StockItem)
                    .values(
                        product_id=body.product_id,
                        low_stock_threshold=body.low_stock_threshold,
                    )
                    .on_conflict_do_nothing(index_elements=[StockItem.product_id])
                )
                item = (
                    await session.scalars(
                        select(StockItem)
                        .where(StockItem.product_id == body.product_id)
                        .with_for_update()
                    )
                ).one()
                error = None
                if item.low_stock_threshold != body.low_stock_threshold:
                    error = ServiceError(
                        409, "STOCK_CONFIGURATION_CONFLICT", "Product stock has different settings"
                    )
                operation = save_operation(
                    session,
                    operation_id,
                    request_hash,
                    "INITIALIZE",
                    actor,
                    stock=stock_view(item),
                    error=error,
                )
    # Rejected results must commit too; raising inside the transaction would lose them.
    return replay(operation)


async def adjust_stock(
    session: AsyncSession, actor: UUID, key: str, body: StockAdjustment
) -> Stock:
    operation_id, request_hash = operation_identity(actor, "inventory.adjust", key, body)
    async with session.begin():
        operation = await existing_operation(session, operation_id, request_hash, "ADJUST")
        if operation is None:
            item = await session.scalar(
                select(StockItem).where(StockItem.product_id == body.product_id).with_for_update()
            )
            error = None
            if item is None:
                error = ServiceError(404, "NOT_FOUND", "Product stock does not exist")
            elif item.version != body.expected_version:
                error = ServiceError(409, "STOCK_VERSION_CONFLICT", "Reload stock before adjusting")
            elif item.on_hand_quantity + body.delta < item.reserved_quantity:
                error = ServiceError(
                    409, "INSUFFICIENT_STOCK", "Adjustment would reduce reserved stock"
                )
            elif item.on_hand_quantity + body.delta > MAX_INTEGER or item.version == MAX_INTEGER:
                error = ServiceError(409, "STOCK_LIMIT_EXCEEDED", "Stock or version limit exceeded")
            if error is not None:
                operation = save_operation(
                    session, operation_id, request_hash, "ADJUST", actor, error=error
                )
            else:
                assert item is not None
                item.on_hand_quantity += body.delta
                item.version += 1
                operation = save_operation(
                    session, operation_id, request_hash, "ADJUST", actor, stock=stock_view(item)
                )
                # Explicit flush ensures the operation FK exists before its movement.
                await session.flush()
                session.add(
                    StockMovement(
                        operation_id=operation_id,
                        product_id=item.product_id,
                        movement_type="RECEIPT" if body.delta > 0 else "ADJUSTMENT",
                        on_hand_delta=body.delta,
                        reserved_delta=0,
                        on_hand_after=item.on_hand_quantity,
                        reserved_after=item.reserved_quantity,
                        reason=body.reason,
                        actor_type="USER",
                        actor_id=actor,
                    )
                )
    return replay(operation)


async def list_stock(
    session: AsyncSession, page: int, page_size: int, low_stock: bool | None
) -> Page[Stock]:
    async with session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        predicate = []
        if low_stock is not None:
            low = StockItem.available_quantity <= StockItem.low_stock_threshold
            predicate.append(low if low_stock else ~low)
        total = await session.scalar(select(func.count()).select_from(StockItem).where(*predicate))
        items = (
            await session.scalars(
                select(StockItem)
                .where(*predicate)
                .order_by(StockItem.created_at.desc(), StockItem.product_id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return Page[Stock](
            items=[stock_view(item) for item in items],
            page=page,
            page_size=page_size,
            total=total or 0,
        )


async def list_movements(
    session: AsyncSession, product_id: UUID, page: int, page_size: int
) -> Page[Movement]:
    async with session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        if await session.get(StockItem, product_id) is None:
            raise ServiceError(404, "NOT_FOUND", "Product stock does not exist")
        predicate = StockMovement.product_id == product_id
        total = await session.scalar(
            select(func.count()).select_from(StockMovement).where(predicate)
        )
        items = (
            await session.scalars(
                select(StockMovement)
                .where(predicate)
                .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return Page[Movement](
            items=[Movement.model_validate(item, from_attributes=True) for item in items],
            page=page,
            page_size=page_size,
            total=total or 0,
        )
