from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.exc import DBAPIError

from commerce_backend_common.errors import ServiceError
from commerce_order.api.actions import execute
from commerce_order.api.dependencies import (
    ActorDependency,
    CustomerActorDependency,
    IdempotencyKey,
    PersistenceDependency,
    QuoteDependency,
    SessionDependency,
    private_response,
)
from commerce_order.api.schemas import (
    ActionResult,
    CartItem,
    CreateOrder,
    Order,
    OrderAccepted,
    OrderPage,
    Quote,
    QuoteInput,
    Reason,
)
from commerce_order.domain.enums import OrderAction, OrderStatus
from commerce_order.domain.transitions import OrderRuleViolation
from commerce_order.services.persistence import PriceChanged
from commerce_order.services.queries import OrderQueries

router = APIRouter(
    prefix="/api/v1/orders", tags=["orders"], dependencies=[Depends(private_response)]
)


@router.post("/quote", response_model=Quote)
async def checkout_quote(
    body: QuoteInput,
    actor: CustomerActorDependency,
    service: QuoteDependency,
    request: Request,
) -> Quote:
    return await service.quote(body, request.state.request_id)


@router.post("", response_model=OrderAccepted, status_code=202)
async def create_order(
    body: CreateOrder,
    actor: CustomerActorDependency,
    service: QuoteDependency,
    store: PersistenceDependency,
    request: Request,
    key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> OrderAccepted:
    async def load_quote() -> Quote:
        items = [
            CartItem(productId=str(item.product_id), quantity=item.quantity) for item in body.items
        ]
        return await service.quote(QuoteInput(items=items), request.state.request_id)

    try:
        result = await store.accept_order(
            actor, key, body, load_quote, correlation_id=UUID(request.state.request_id)
        )
    except PriceChanged as exc:
        raise ServiceError(
            409,
            "PRICE_CHANGED",
            "Prices changed; confirm the new quote",
            details={"quote": exc.quote.model_dump(mode="json")},
        ) from exc
    except OrderRuleViolation as exc:
        status = 403 if exc.code == "FORBIDDEN" else 409
        raise ServiceError(status, exc.code, "Request conflicts with the accepted order") from exc
    except DBAPIError as exc:
        raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Order storage is unavailable") from exc
    return OrderAccepted.model_validate(result.body)


@router.get("", response_model=OrderPage)
async def customer_orders(
    actor: ActorDependency,
    session: SessionDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    status: OrderStatus | None = None,
) -> OrderPage:
    return await OrderQueries(session).page(actor, page=page, page_size=page_size, status=status)


@router.get("/{id}", response_model=Order)
async def customer_order(id: UUID, actor: ActorDependency, session: SessionDependency) -> Order:
    return await OrderQueries(session).detail(actor, id)


@router.post("/{id}/cancel", response_model=ActionResult, status_code=202)
async def cancel_order(
    id: UUID,
    body: Reason,
    actor: CustomerActorDependency,
    store: PersistenceDependency,
    key: IdempotencyKey,
) -> ActionResult:
    return await execute(actor, store, id, OrderAction.CANCEL, key, body)
