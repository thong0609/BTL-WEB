"""Service factory; DB resources are optional and bounded by lifespan."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from commerce_backend_common.application import build_app, combine_lifespans
from commerce_backend_common.database_lifespan import database_lifespan
from commerce_catalog.api import admin_router, internal_router, public_router
from commerce_catalog.db import SPEC
from commerce_catalog.settings import Settings


def create_app(
    settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    config = settings if settings is not None else Settings()

    def client(origin: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=origin,
            timeout=httpx.Timeout(config.http_timeout_seconds),
            limits=httpx.Limits(max_connections=config.http_max_connections),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    @asynccontextmanager
    async def upstreams(app: FastAPI) -> AsyncIterator[None]:
        async with client(str(config.identity_base_url)) as identity:
            app.state.identity_client = identity
            yield

    app = build_app(
        config,
        combine_lifespans(database_lifespan(config, SPEC), upstreams),
    )
    app.include_router(public_router)
    app.include_router(admin_router)
    app.include_router(internal_router)
    return app
