"""Gateway lifespan owns one bounded async HTTP client."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from commerce_backend_common.application import build_app
from commerce_gateway.api import router
from commerce_gateway.orders import router as orders_router
from commerce_gateway.settings import Settings


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    order_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    config = settings if settings is not None else Settings()

    @asynccontextmanager
    async def resources(app: FastAPI) -> AsyncIterator[None]:
        async with (
            httpx.AsyncClient(
                base_url=str(config.catalog_base_url),
                timeout=httpx.Timeout(config.http_timeout_seconds),
                limits=httpx.Limits(max_connections=config.http_max_connections),
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client,
            httpx.AsyncClient(
                base_url=str(config.order_base_url),
                timeout=httpx.Timeout(config.http_timeout_seconds),
                limits=httpx.Limits(max_connections=config.http_max_connections),
                follow_redirects=False,
                trust_env=False,
                transport=order_transport,
            ) as order_client,
        ):
            app.state.catalog_client = client
            app.state.order_client = order_client
            yield

    app = build_app(config, resources)
    app.include_router(router)
    app.include_router(orders_router)
    return app
