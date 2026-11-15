"""Payment-owned HTTP routes from docs/contracts/HTTP-API.md."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from commerce_backend_common.errors import ServiceError
from commerce_payment.db import session_dependency
from commerce_payment.models import (
    DemoConfiguration,
    DemoConfigurationHistory,
    PaymentAttempt,
    RefundAttempt,
)
from commerce_payment.security import customer_id, require_demo_admin, require_internal
from commerce_payment.settings import Settings
from commerce_payment.views import DemoScenario, PaymentView, RefundView

router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(session_dependency)]


def _settings(request: Request) -> Settings:
    settings = request.app.state.settings
    assert isinstance(settings, Settings)
    return settings


@router.get("/payments/{payment_id}", response_model=PaymentView)
async def get_payment(payment_id: UUID, request: Request, session: SessionDep) -> PaymentView:
    caller = customer_id(request)
    payment = await session.scalar(select(PaymentAttempt).where(PaymentAttempt.id == payment_id))
    if payment is None or payment.customer_id != caller:
        raise ServiceError(404, "NOT_FOUND", "Resource not found")
    refund = await session.scalar(
        select(RefundAttempt).where(RefundAttempt.payment_id == payment.id)
    )
    return _payment_view(payment, refund)


@router.get(
    "/internal/payments/by-order/{order_id}",
    response_model=PaymentView,
    tags=["internal"],
)
async def get_payment_by_order(
    order_id: UUID, request: Request, session: SessionDep
) -> PaymentView:
    require_internal(request, _settings(request))
    payment = await session.scalar(
        select(PaymentAttempt).where(PaymentAttempt.order_id == order_id)
    )
    if payment is None:
        raise ServiceError(404, "NOT_FOUND", "Resource not found")
    refund = await session.scalar(
        select(RefundAttempt).where(RefundAttempt.payment_id == payment.id)
    )
    return _payment_view(payment, refund)


@router.get("/admin/demo/payment-scenario", response_model=DemoScenario, tags=["Admin"])
async def get_demo_scenario(request: Request, session: SessionDep) -> DemoScenario:
    require_demo_admin(request, _settings(request))
    config = await session.get(DemoConfiguration, 1)
    if config is None:
        raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Demo configuration is missing")
    return DemoScenario(
        payment_scenario=config.payment_scenario,
        refund_scenario=config.refund_scenario,
        delay_seconds=config.delay_seconds,
    )


@router.put("/admin/demo/payment-scenario", response_model=DemoScenario, tags=["Admin"])
async def put_demo_scenario(
    body: DemoScenario, request: Request, session: SessionDep
) -> DemoScenario:
    require_demo_admin(request, _settings(request))
    async with session.begin():
        config = await session.get(DemoConfiguration, 1, with_for_update=True)
        if config is None:
            raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Demo configuration is missing")
        now = datetime.now(UTC)
        actor_raw = request.headers.get("X-User-Id", "").strip()
        actor_id = UUID(actor_raw) if actor_raw else None
        config.payment_scenario = body.payment_scenario
        config.refund_scenario = body.refund_scenario
        config.delay_seconds = body.delay_seconds
        config.version += 1
        config.updated_by = actor_id
        config.updated_at = now
        session.add(
            DemoConfigurationHistory(
                id=uuid4(),
                configuration_id=config.id,
                version=config.version,
                snapshot=body.model_dump(mode="json", by_alias=True),
                actor_id=actor_id,
                created_at=now,
            )
        )
    return body


def _payment_view(payment: PaymentAttempt, refund: RefundAttempt | None) -> PaymentView:
    refund_view = None
    if refund is not None:
        refund_view = RefundView(id=refund.id, status=refund.status, amount=refund.amount)
    return PaymentView(
        id=payment.id,
        order_id=payment.order_id,
        method=payment.method,
        amount=payment.amount,
        currency="VND",
        status=payment.status,
        version=payment.version,
        refund=refund_view,
    )
