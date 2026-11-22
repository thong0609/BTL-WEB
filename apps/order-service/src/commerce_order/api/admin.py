from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from commerce_order.api.actions import execute
from commerce_order.api.dependencies import (
    ActorDependency,
    AdminActorDependency,
    IdempotencyKey,
    PersistenceDependency,
    SessionDependency,
    no_action_body,
    private_response,
)
from commerce_order.api.schemas import ActionResult, Complete, Order, OrderPage, Reason
from commerce_order.domain.enums import OrderAction, OrderStatus
from commerce_order.services.queries import OrderQueries

router = APIRouter(
    prefix="/api/v1/admin/orders", tags=["Admin"], dependencies=[Depends(private_response)]
)


@router.get("", response_model=OrderPage)
async def admin_orders(
    actor: ActorDependency,
    session: SessionDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    status: OrderStatus | None = None,
    q: str | None = None,
) -> OrderPage:
    return await OrderQueries(session).page(
        actor, admin=True, page=page, page_size=page_size, status=status, q=q
    )


@router.get("/{id}", response_model=Order)
async def admin_order(id: UUID, actor: ActorDependency, session: SessionDependency) -> Order:
    return await OrderQueries(session).detail(actor, id, admin=True)


@router.post("/{id}/confirm", response_model=ActionResult, dependencies=[Depends(no_action_body)])
async def confirm(
    id: UUID, actor: AdminActorDependency, store: PersistenceDependency, key: IdempotencyKey
) -> ActionResult:
    return await execute(actor, store, id, OrderAction.CONFIRM, key)


@router.post("/{id}/cancel", response_model=ActionResult, status_code=202)
async def cancel(
    id: UUID,
    body: Reason,
    actor: AdminActorDependency,
    store: PersistenceDependency,
    key: IdempotencyKey,
) -> ActionResult:
    return await execute(actor, store, id, OrderAction.CANCEL, key, body)


@router.post(
    "/{id}/dispatch",
    response_model=ActionResult,
    status_code=202,
    dependencies=[Depends(no_action_body)],
)
async def dispatch(
    id: UUID, actor: AdminActorDependency, store: PersistenceDependency, key: IdempotencyKey
) -> ActionResult:
    return await execute(actor, store, id, OrderAction.DISPATCH, key)


@router.post("/{id}/complete", response_model=ActionResult, status_code=202)
async def complete(
    id: UUID,
    body: Complete,
    actor: AdminActorDependency,
    store: PersistenceDependency,
    key: IdempotencyKey,
) -> ActionResult:
    return await execute(actor, store, id, OrderAction.COMPLETE, key, body)


@router.post("/{id}/exceptions", response_model=ActionResult)
async def exception(
    id: UUID,
    body: Reason,
    actor: AdminActorDependency,
    store: PersistenceDependency,
    key: IdempotencyKey,
) -> ActionResult:
    return await execute(actor, store, id, OrderAction.RECORD_EXCEPTION, key, body)
