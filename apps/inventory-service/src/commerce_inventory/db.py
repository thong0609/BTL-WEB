"""inventory-service metadata belongs only to commerce_inventory."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from commerce_backend_common.database import database_spec
from commerce_backend_common.database_lifespan import get_session

SPEC = database_spec("inventory-service")


class Base(DeclarativeBase):
    metadata = MetaData(
        schema=SPEC.schema,
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        },
    )


# Import this dependency from the owning service; models are never shared.
session_dependency = get_session
