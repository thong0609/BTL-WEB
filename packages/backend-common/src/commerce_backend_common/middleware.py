"""ASGI request context outside CORS, with sanitized exception handling."""

from time import perf_counter
from uuid import UUID, uuid4

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from commerce_backend_common.errors import error_response


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, service_name: str) -> None:
        self.app = app
        self.service_name = service_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = Headers(scope=scope).get("x-request-id", "")
        try:
            request_id = str(UUID(supplied))
        except ValueError:
            request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        tokens = structlog.contextvars.bind_contextvars(request_id=request_id)
        log = structlog.get_logger().bind(service=self.service_name)
        started = perf_counter()
        response_started = False
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal response_started, status
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-Id"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            log.error("request_failed", error_type=type(exc).__name__)
            if response_started:
                raise
            response = error_response(request_id, 500, "INTERNAL_ERROR", "Internal server error")
            await response(scope, receive, send_with_id)
        finally:
            # Route template only; never query string, raw URL, body or exception text.
            route = getattr(scope.get("route"), "path", "unmatched")
            log.info(
                "request_completed",
                method=scope["method"],
                route=route,
                status=status,
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
            structlog.contextvars.reset_contextvars(**tokens)
