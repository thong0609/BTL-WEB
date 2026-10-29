"""FastAPI construction and health contracts, without infrastructure clients."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import structlog
from fastapi import APIRouter, FastAPI, Request
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from commerce_backend_common.errors import register_error_handlers
from commerce_backend_common.logging import configure_logging
from commerce_backend_common.middleware import RequestContextMiddleware
from commerce_backend_common.schemas import ApiModel
from commerce_backend_common.settings import ServiceSettings

type AppLifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


class HealthResponse(ApiModel):
    service: str
    status: str
    checks: dict[str, str]


def build_app(settings: ServiceSettings, resources: AppLifespan | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        app.state.started = True
        log = structlog.get_logger().bind(service=settings.service_name)
        try:
            if resources is not None:
                async with resources(app):
                    log.info("service_started")
                    yield
            else:
                log.info("service_started")
                yield
        finally:
            app.state.started = False
            log.info("service_stopped")

    app = FastAPI(title=settings.service_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.started = False
    register_error_handlers(app)
    app.add_middleware(RequestContextMiddleware, service_name=settings.service_name)
    # CORS outside the exception-sanitizing middleware includes CORS on 500 responses.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
        expose_headers=["X-Request-Id"],
    )
    router = APIRouter(tags=["health"])

    @router.get("/health/live", response_model=HealthResponse)
    async def live() -> HealthResponse:
        return HealthResponse(service=settings.service_name, status="alive", checks={})

    @router.get("/health/ready", response_model=HealthResponse)
    async def ready(request: Request) -> JSONResponse:
        checks = {"lifespan": "ready" if request.app.state.started else "not_started"}
        for dependency, enabled, url in (
            ("database", settings.database_enabled, settings.database_url),
            ("broker", settings.broker_enabled, settings.broker_url),
        ):
            checks[dependency] = (
                ("check_not_implemented" if url else "missing_configuration")
                if enabled
                else "disabled"
            )
        ok = all(value in {"ready", "disabled"} for value in checks.values())
        body = HealthResponse(
            service=settings.service_name,
            status="ready" if ok else "not_ready",
            checks=checks,
        )
        return JSONResponse(body.model_dump(mode="json"), status_code=200 if ok else 503)

    app.include_router(router)
    return app
