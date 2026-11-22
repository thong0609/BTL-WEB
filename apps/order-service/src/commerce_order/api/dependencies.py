"""Fail-closed authentication seam; no client-supplied identity headers are trusted."""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from commerce_backend_common.database import Database
from commerce_backend_common.errors import ServiceError
from commerce_order.db import session_dependency
from commerce_order.domain.enums import ActorRole
from commerce_order.domain.transitions import Actor
from commerce_order.services.persistence import OrderPersistence
from commerce_order.services.quote import QuoteService

type TokenVerifier = Callable[[str], Awaitable[Actor]]
bearer = HTTPBearer(auto_error=False)


async def current_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Actor:
    if credentials is None:
        raise ServiceError(401, "AUTH_INVALID", "Authentication required")
    verifier: TokenVerifier | None = request.app.state.token_verifier
    if verifier is None:
        raise ServiceError(503, "AUTH_UNAVAILABLE", "Token verification is not configured")
    actor = await verifier(credentials.credentials)
    if (
        not isinstance(actor, Actor)
        or not isinstance(actor.user_id, UUID)
        or actor.role not in {ActorRole.CUSTOMER, ActorRole.ADMIN}
    ):
        raise ServiceError(401, "AUTH_INVALID", "Invalid authenticated principal")
    return actor


def private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


ActorDependency = Annotated[Actor, Depends(current_actor)]
SessionDependency = Annotated[AsyncSession, Depends(session_dependency)]


async def customer_actor(actor: ActorDependency) -> Actor:
    if actor.role != ActorRole.CUSTOMER:
        raise ServiceError(403, "FORBIDDEN", "Permission denied")
    return actor


def quote_service(request: Request) -> QuoteService:
    service: QuoteService = request.app.state.quote_service
    return service


def persistence(request: Request) -> OrderPersistence:
    database: Database | None = request.app.state.database
    if database is None:
        raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Database is not configured")
    return OrderPersistence(database.session_factory)


CustomerActorDependency = Annotated[Actor, Depends(customer_actor)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]
QuoteDependency = Annotated[QuoteService, Depends(quote_service)]
PersistenceDependency = Annotated[OrderPersistence, Depends(persistence)]


async def admin_actor(actor: ActorDependency) -> Actor:
    if actor.role != ActorRole.ADMIN:
        raise ServiceError(403, "FORBIDDEN", "Permission denied")
    return actor


AdminActorDependency = Annotated[Actor, Depends(admin_actor)]


async def no_action_body(request: Request) -> None:
    import json

    raw = await request.body()
    if not raw:
        return
    try:
        body = json.loads(raw)
    except ValueError:
        raise ServiceError(400, "VALIDATION_ERROR", "Invalid action body") from None
    if body is not None and body != {}:
        raise ServiceError(400, "VALIDATION_ERROR", "This action does not accept input fields")
