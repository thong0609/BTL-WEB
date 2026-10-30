"""Loopback smoke-only fixture: actual gateway plus a header/cookie echo route."""

import os

import uvicorn
from fastapi import Request
from starlette.responses import JSONResponse

from commerce_gateway.main import create_app

app = create_app()


@app.get("/api/v1/__smoke/echo")
async def echo(request: Request) -> JSONResponse:
    response = JSONResponse(
        {
            "cookie": request.cookies.get("smoke"),
            "authorization": request.headers.get("authorization"),
            "requestId": request.state.request_id,
            "query": request.query_params.get("value"),
        }
    )
    response.set_cookie("smoke_reply", "ok", httponly=True, samesite="lax")
    return response


if __name__ == "__main__":
    if os.environ.get("APP_ENV") != "test":
        raise SystemExit("Smoke fixture requires APP_ENV=test")
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["HTTP_PORT"]), access_log=False)
