"""Attach a service-owned engine to app lifespan without touching data at import time."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession

from commerce_backend_common.application import AppLifespan
from commerce_backend_common.database import (
    Database,
    DatabaseConfigurationError,
    DatabaseSettings,
    DatabaseSpec,
)
from commerce_backend_common.errors import ServiceError


def database_lifespan(settings: DatabaseSettings, spec: DatabaseSpec) -> AppLifespan:
    @asynccontextmanager
    async def resources(app: FastAPI) -> AsyncIterator[None]:
        database: Database | None = None
        checks: dict[str, Callable[[], Awaitable[str]]] = app.state.readiness_checks
        if settings.database_enabled and settings.database_url:
            try:
                database = Database(settings, spec)
            except DatabaseConfigurationError:

                async def invalid() -> str:
                    return "invalid_configuration"

                checks["database"] = invalid
            else:
                checks["database"] = database.readiness
        app.state.database = database
        try:
            yield
        finally:
            if database is not None:
                await database.close()
            checks.pop("database", None)
            app.state.database = None

    return resources


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database | None = getattr(request.app.state, "database", None)
    if database is None:
        raise ServiceError(503, "DATABASE_UNAVAILABLE", "Database is not configured")
    async with database.session() as session:
        yield session
