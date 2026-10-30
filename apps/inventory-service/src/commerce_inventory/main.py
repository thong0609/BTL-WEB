"""Service factory; DB resources are optional and bounded by lifespan."""

from fastapi import FastAPI

from commerce_backend_common.application import build_app, combine_lifespans
from commerce_backend_common.database_lifespan import database_lifespan
from commerce_backend_common.messaging_lifespan import broker_lifespan
from commerce_inventory.db import SPEC
from commerce_inventory.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else Settings()
    return build_app(
        config, combine_lifespans(database_lifespan(config, SPEC), broker_lifespan(config))
    )
