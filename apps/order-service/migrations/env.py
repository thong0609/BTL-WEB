"""Migrations run explicitly with this service's migrator credentials."""

from commerce_backend_common.migrations import run_migrations
from commerce_order.db import SPEC, Base
from commerce_order.settings import Settings

run_migrations(Settings(), SPEC, Base.metadata)
