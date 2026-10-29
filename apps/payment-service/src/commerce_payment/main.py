"""Service factory; DB resources are optional and bounded by lifespan."""

from fastapi import FastAPI

from commerce_backend_common.application import build_app
from commerce_backend_common.database_lifespan import database_lifespan
from commerce_payment.db import SPEC
from commerce_payment.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else Settings()
    return build_app(config, database_lifespan(config, SPEC))
