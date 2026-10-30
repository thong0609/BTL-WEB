"""API transport client: no topology mutation and no consumers on startup."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from commerce_backend_common.application import AppLifespan
from commerce_backend_common.messaging import Broker, BrokerConfigurationError
from commerce_backend_common.settings import ServiceSettings


def broker_lifespan(settings: ServiceSettings) -> AppLifespan:
    @asynccontextmanager
    async def resources(app: FastAPI) -> AsyncIterator[None]:
        broker: Broker | None = None
        checks: dict[str, Callable[[], Awaitable[str]]] = app.state.readiness_checks
        if settings.broker_enabled and settings.broker_url:
            try:
                broker = Broker(settings)
            except BrokerConfigurationError:

                async def invalid() -> str:
                    return "invalid_configuration"

                checks["broker"] = invalid
            else:
                # First actual connection happens on readiness/publish, not import.
                checks["broker"] = broker.readiness
        app.state.broker = broker
        try:
            yield
        finally:
            checks.pop("broker", None)
            if broker is not None:
                await broker.close()
            app.state.broker = None

    return resources
