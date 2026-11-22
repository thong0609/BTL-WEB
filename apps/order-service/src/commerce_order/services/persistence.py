"""Atomic acceptance primitives; no HTTP endpoints or external side effects are started here."""

from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from commerce_order.api.schemas import Complete, CreateOrder, Quote
from commerce_order.domain.enums import (
    ActorRole,
    OrderAction,
    OrderStatus,
    PaymentStep,
    StockStep,
    WorkflowPhase,
    WorkflowState,
)
from commerce_order.domain.transitions import Actor, OrderRuleViolation, ensure_action_allowed
from commerce_order.models import (
    HistoryActorType,
    IdempotencyRequest,
    OrderActionRequest,
    OrderItem,
    OrderRecord,
    OrderStatusHistory,
    OrderWorkflow,
    OutboxMessage,
)
from commerce_order.repositories.idempotency import IdempotencyRepository
from commerce_order.repositories.orders import LockedOrder, OrderRepository
from commerce_order.services.idempotency import (
    ActionPayload,
    action_hash,
    creation_hash,
    validate_key,
)


@dataclass(frozen=True)
class StoredResponse:
    status_code: int
    body: dict[str, JsonValue]
    replayed: bool = False


def _replay(record: IdempotencyRequest | OrderActionRequest, request_hash: str) -> StoredResponse:
    if record.request_hash != request_hash:
        raise OrderRuleViolation("IDEMPOTENCY_CONFLICT")
    return StoredResponse(record.response_status, deepcopy(record.response_body), replayed=True)


class PriceChanged(OrderRuleViolation):
    def __init__(self, quote: Quote) -> None:
        self.quote = quote
        super().__init__("PRICE_CHANGED")


def _check_quote(request: CreateOrder, quote: Quote) -> None:
    current = {item.product_id: item for item in quote.items}
    if len(current) != len(request.items):
        raise PriceChanged(quote)
    for expected in request.items:
        item = current.get(expected.product_id)
        if item is None or (
            item.quantity != expected.quantity
            or item.unit_price_amount != expected.expected_unit_price_amount
            or item.catalog_version != expected.expected_catalog_version
        ):
            raise PriceChanged(quote)
    if request.expected_shipping_fee_amount != quote.shipping_fee_amount:
        raise PriceChanged(quote)


class OrderPersistence:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def accept_order(
        self,
        actor: Actor,
        key: str,
        request: CreateOrder,
        load_quote: Callable[[], Awaitable[Quote]],
        *,
        correlation_id: UUID | None = None,
    ) -> StoredResponse:
        """The checkout caller supplies load_quote; replay never calls it.

        A complete attempted write lives inside a savepoint. The unique-key loser
        rolls it all back, then reads the committed winner using READ COMMITTED.
        """
        if actor.role != ActorRole.CUSTOMER:
            raise OrderRuleViolation("FORBIDDEN")
        validate_key(key)
        digest = creation_hash(request)
        async with self.sessions() as session, session.begin():
            existing = await IdempotencyRepository(session).creation(actor.user_id, key)
            if existing is not None:
                return _replay(existing, digest)
        try:
            quote = await load_quote()  # No DB transaction/lock is held during network I/O.
        except Exception:
            # A concurrent winner can have accepted the request while this caller read Catalog.
            async with self.sessions() as session, session.begin():
                existing = await IdempotencyRepository(session).creation(actor.user_id, key)
                if existing is not None:
                    return _replay(existing, digest)
            raise
        async with self.sessions() as session, session.begin():
            existing = await IdempotencyRepository(session).creation(actor.user_id, key)
            if existing is not None:
                return _replay(existing, digest)
            _check_quote(request, quote)
            try:
                async with session.begin_nested():
                    result = await self._write_order(
                        session, actor, key, request, quote, digest, correlation_id=correlation_id
                    )
                return result
            except IntegrityError as exc:
                cause = getattr(exc.orig, "__cause__", None)
                if (
                    getattr(exc.orig, "sqlstate", None) != "23505"
                    or getattr(cause, "constraint_name", None)
                    != "uq_idempotency_requests_customer_id"
                ):
                    raise
                # Never convert unrelated constraints into a successful replay.
                existing = await IdempotencyRepository(session).creation(actor.user_id, key)
                if existing is None:
                    raise
                return _replay(existing, digest)

    async def _write_order(
        self,
        session: AsyncSession,
        actor: Actor,
        key: str,
        request: CreateOrder,
        quote: Quote,
        digest: str,
        *,
        correlation_id: UUID | None = None,
    ) -> StoredResponse:
        order_id, operation_id = uuid4(), uuid4()
        correlation_id = correlation_id if correlation_id is not None else uuid4()
        order = OrderRecord(
            id=order_id,
            order_number=order_id.hex.upper(),
            customer_id=actor.user_id,
            status=OrderStatus.PROCESSING,
            payment_method=request.payment_method,
            recipient_name=request.recipient.name,
            recipient_phone=request.recipient.phone,
            shipping_address=request.recipient.address,
            customer_note=request.note or None,
            subtotal_amount=quote.subtotal_amount,
            shipping_fee_amount=quote.shipping_fee_amount,
            total_amount=quote.total_amount,
            currency=quote.currency,
        )
        session.add(order)
        await session.flush()
        body: dict[str, JsonValue] = {
            "orderId": str(order_id),
            "orderNumber": order.order_number,
            "status": "PROCESSING",
        }
        session.add_all(
            [
                OrderItem(
                    order_id=order_id,
                    product_id=item.product_id,
                    product_sku=item.sku,
                    product_name=item.name,
                    catalog_version=item.catalog_version,
                    unit_price_amount=item.unit_price_amount,
                    quantity=item.quantity,
                    line_total_amount=item.line_total_amount,
                )
                for item in quote.items
            ]
        )
        session.add_all(
            [
                OrderWorkflow(
                    order_id=order_id,
                    phase=WorkflowPhase.CHECKOUT,
                    state=WorkflowState.WAITING,
                    stock_step=StockStep.RESERVE_PENDING,
                    payment_step=PaymentStep.NOT_REQUESTED,
                    reserve_operation_id=operation_id,
                    correlation_id=correlation_id,
                ),
                OrderStatusHistory(
                    order_id=order_id,
                    from_status=None,
                    to_status=OrderStatus.PROCESSING,
                    actor_type=HistoryActorType.CUSTOMER,
                    actor_id=actor.user_id,
                    correlation_id=correlation_id,
                ),
                IdempotencyRequest(
                    customer_id=actor.user_id,
                    scope="CREATE_ORDER",
                    idempotency_key=key,
                    request_hash=digest,
                    order_id=order_id,
                    response_status=202,
                    response_body=body,
                ),
                OutboxMessage(
                    message_type="ReserveStock",
                    aggregate_type="ORDER",
                    aggregate_id=order_id,
                    exchange_name="commerce.commands",
                    routing_key="inventory.reserve",
                    correlation_id=correlation_id,
                    payload={
                        "orderId": str(order_id),
                        "operationId": str(operation_id),
                        "items": [
                            {"productId": str(item.product_id), "quantity": item.quantity}
                            for item in quote.items
                        ],
                    },
                ),
            ]
        )
        await session.flush()
        return StoredResponse(202, body)

    async def accept_action(
        self,
        actor: Actor,
        order_id: UUID,
        action: OrderAction,
        key: str,
        payload: ActionPayload,
        apply: Callable[[AsyncSession, LockedOrder], Awaitable[StoredResponse]],
    ) -> StoredResponse:
        """apply may only write in this transaction, never call external services.

        The lock, authorization, replay, response record and commit are centralized here.
        """
        validate_key(key)
        digest = action_hash(action, payload)
        if actor.role != ActorRole.ADMIN and action != OrderAction.CANCEL:
            raise OrderRuleViolation("FORBIDDEN")
        async with self.sessions() as session, session.begin():
            locked = await OrderRepository(session).lock(order_id)
            if locked is None or (
                actor.role == ActorRole.CUSTOMER and locked.order.customer_id != actor.user_id
            ):
                raise OrderRuleViolation("NOT_FOUND")
            existing = await IdempotencyRepository(session).action(
                actor.user_id, order_id, action, key
            )
            if existing is not None:
                return _replay(existing, digest)
            already_cancelled = (
                action == OrderAction.CANCEL and locked.order.status == OrderStatus.CANCELLED
            )
            if already_cancelled:
                response = StoredResponse(
                    202,
                    {
                        "orderId": str(order_id),
                        "status": locked.order.status.value,
                        "workflowState": locked.workflow.state.value,
                    },
                )
            else:
                ensure_action_allowed(locked.facts(), actor, action)
                if isinstance(payload, Complete):
                    payload.validate_for_payment_method(locked.order.payment_method)
                response = await apply(session, locked)
                locked.order.version += 1
                locked.workflow.version += 1
            session.add(
                OrderActionRequest(
                    order_id=order_id,
                    actor_id=actor.user_id,
                    action=action,
                    request_body=payload.model_dump(mode="json") if payload is not None else None,
                    idempotency_key=key,
                    request_hash=digest,
                    response_status=response.status_code,
                    response_body=response.body,
                )
            )
            await session.flush()
            return response
