"""Service factory; DB resources are optional and bounded by lifespan."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from commerce_backend_common.application import build_app, combine_lifespans
from commerce_backend_common.database_lifespan import database_lifespan
from commerce_backend_common.messaging_lifespan import broker_lifespan
from commerce_order.api.admin import router as admin_router
from commerce_order.api.customer import router as customer_router
from commerce_order.api.dependencies import TokenVerifier
from commerce_order.clients.catalog import CatalogClient
from commerce_order.db import SPEC
from commerce_order.services.quote import QuoteService
from commerce_order.settings import Settings


def create_app(
    settings: Settings | None = None,
    *,
    token_verifier: TokenVerifier | None = None,
    catalog_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    config = settings if settings is not None else Settings()

    @asynccontextmanager
    async def catalog_resources(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(
            base_url=str(config.catalog_base_url),
            timeout=httpx.Timeout(config.http_timeout_seconds),
            limits=httpx.Limits(max_connections=config.http_max_connections),
            follow_redirects=False,
            trust_env=False,
            transport=catalog_transport,
        ) as client:
            app.state.catalog_client = client
            app.state.quote_service = QuoteService(
                CatalogClient(client, config.catalog_service_token), config.shipping_fee_amount
            )
            yield

    app = build_app(
        config,
        combine_lifespans(
            database_lifespan(config, SPEC), broker_lifespan(config), catalog_resources
        ),
    )
    app.state.token_verifier = token_verifier
    app.include_router(customer_router)
    app.include_router(admin_router)
    return app
