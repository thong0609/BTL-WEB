"""Public errors are sanitized; exception messages and inputs stay private."""

from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


def error_response(
    request_id: str,
    status: int,
    code: str,
    message: str,
    *,
    details: object | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, object] = {"code": code, "message": message, "requestId": request_id}
    if details is not None:
        body["details"] = details
    return JSONResponse(body, status_code=status, headers=headers)


class ServiceError(Exception):
    def __init__(self, status: int, code: str, public_message: str) -> None:
        self.status = status
        self.code = code
        self.public_message = public_message
        super().__init__(code)


def register_error_handlers(app: FastAPI) -> None:
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's input/ctx/msg can contain secrets or user-controlled values.
        details = [
            {"field": ".".join(str(part) for part in item["loc"]), "type": item["type"]}
            for item in exc.errors()
        ]
        return error_response(
            request.state.request_id,
            400,
            "VALIDATION_ERROR",
            "Invalid request data",
            details={"fields": details},
        )

    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        mapping = {
            401: ("AUTH_REQUIRED", "Authentication required"),
            403: ("FORBIDDEN", "Permission denied"),
            404: ("NOT_FOUND", "Resource not found"),
            405: ("METHOD_NOT_ALLOWED", "Method not allowed"),
            409: ("CONFLICT", "Request conflicts with current state"),
        }
        code, message = mapping.get(
            exc.status_code, ("HTTP_ERROR", "Request could not be processed")
        )
        return error_response(
            request.state.request_id, exc.status_code, code, message, headers=exc.headers
        )

    async def service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return error_response(request.state.request_id, exc.status, exc.code, exc.public_message)

    app.add_exception_handler(RequestValidationError, validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_error)  # type: ignore[arg-type]
    app.add_exception_handler(ServiceError, service_error)  # type: ignore[arg-type]
