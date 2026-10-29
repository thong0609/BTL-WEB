"""FastAPI factory; no DB or broker connection is opened in setup step 2."""

from fastapi import FastAPI

from commerce_backend_common.application import build_app
from commerce_inventory.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    return build_app(settings if settings is not None else Settings())
