"""Alembic mechanics restricted to one allowlisted schema per invocation."""

import asyncio
from typing import Any

from alembic import context
from sqlalchemy import Connection, MetaData, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from commerce_backend_common.database import (
    DatabaseConfigurationError,
    DatabaseSettings,
    DatabaseSpec,
    postgres_url,
    ssl_context,
)
from commerce_backend_common.database_bootstrap import identifier


def migration_options(spec: DatabaseSpec, metadata: MetaData) -> dict[str, Any]:
    if any(table.schema != spec.schema for table in metadata.tables.values()):
        raise DatabaseConfigurationError("Migration metadata includes a foreign schema")

    def include_name(name: str | None, type_: str, parents: dict[str, str | None]) -> bool:
        if type_ == "schema":
            return name == spec.schema
        if type_ == "table":
            return parents.get("schema_name") == spec.schema and name != "alembic_version"
        return True

    return {
        "target_metadata": metadata,
        "include_schemas": True,
        "include_name": include_name,
        "version_table_schema": spec.schema,
        "version_table": "alembic_version",
        "compare_type": True,
    }


def run_migrations(settings: DatabaseSettings, spec: DatabaseSpec, metadata: MetaData) -> None:
    if settings.db_schema != spec.schema:
        raise DatabaseConfigurationError("Migration schema does not belong to this service")
    if settings.migration_database_url is None:
        raise DatabaseConfigurationError(
            "MIGRATION_DATABASE_URL is required; runtime URL is not used"
        )
    url = postgres_url(settings.migration_database_url, spec.migrator)
    options = migration_options(spec, metadata)
    if context.is_offline_mode():
        # Offline output has no URL/password. Schema/roles must already exist from bootstrap.
        context.configure(dialect_name="postgresql", literal_binds=True, **options)
        with context.begin_transaction():
            context.execute(f"SET LOCAL ROLE {identifier(spec.owner)}")
            context.run_migrations()
            context.execute(
                f"REVOKE ALL ON {identifier(spec.schema)}.alembic_version "
                f"FROM {identifier(spec.runtime)}"
            )
        return

    async def online() -> None:
        engine = create_async_engine(
            url,
            poolclass=NullPool,
            hide_parameters=True,
            connect_args={
                "ssl": ssl_context(settings.db_ssl_mode, url.host, settings.db_ssl_ca_file),
                "timeout": settings.db_connect_timeout_seconds,
                "command_timeout": settings.db_query_timeout_seconds,
            },
        )
        try:
            async with engine.connect() as connection:
                # A session advisory lock serializes migrations for just this schema.
                await connection.execute(
                    text("SELECT pg_advisory_lock(hashtext(:key))"),
                    {"key": f"commerce:migrate:{spec.schema}"},
                )
                await connection.commit()
                try:
                    owner = await connection.scalar(
                        text(
                            "SELECT pg_get_userbyid(nspowner) FROM pg_namespace "
                            "WHERE nspname=:schema"
                        ),
                        {"schema": spec.schema},
                    )
                    if owner != spec.owner:
                        raise DatabaseConfigurationError("Bootstrap schema/owner before migration")
                    await connection.execute(text(f"SET ROLE {identifier(spec.owner)}"))
                    await connection.commit()

                    def migrate(sync_connection: Connection) -> None:
                        context.configure(connection=sync_connection, **options)
                        with context.begin_transaction():
                            context.run_migrations()
                            context.execute(
                                f"REVOKE ALL ON {identifier(spec.schema)}.alembic_version "
                                f"FROM {identifier(spec.runtime)}"
                            )

                    await connection.run_sync(migrate)
                    await connection.commit()
                finally:
                    await connection.rollback()
                    await connection.execute(text("RESET ROLE"))
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(hashtext(:key))"),
                        {"key": f"commerce:migrate:{spec.schema}"},
                    )
                    await connection.commit()
        finally:
            await engine.dispose()

    asyncio.run(online())
