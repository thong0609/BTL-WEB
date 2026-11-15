"""Migrations run explicitly with this service's migrator credentials."""

from commerce_backend_common.migrations import run_migrations
from commerce_payment.db import SPEC
from commerce_payment.models import Base
from commerce_payment.settings import Settings

run_migrations(Settings(), SPEC, Base.metadata)
