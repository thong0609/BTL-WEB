"""Technical PostgreSQL plumbing. No business models or cross-service sessions."""

import os
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from sqlalchemy import URL, make_url, text
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from commerce_backend_common.settings import ServiceSettings


@dataclass(frozen=True)
class DatabaseSpec:
    service: str
    schema: str
    role_prefix: str

    @property
    def owner(self) -> str:
        return f"{self.role_prefix}_owner"

    @property
    def migrator(self) -> str:
        return f"{self.role_prefix}_migrator"

    @property
    def runtime(self) -> str:
        return f"{self.role_prefix}_runtime"


DATABASE_SPECS = (
    DatabaseSpec("identity-service", "commerce_identity", "identity"),
    DatabaseSpec("catalog-service", "commerce_catalog", "catalog"),
    DatabaseSpec("inventory-service", "commerce_inventory", "inventory"),
    DatabaseSpec("order-service", "commerce_orders", "order"),
    DatabaseSpec("payment-service", "commerce_payments", "payment"),
)


def database_spec(service: str) -> DatabaseSpec:
    for spec in DATABASE_SPECS:
        if spec.service == service:
            return spec
    raise ValueError("Service does not own a database schema")


class DatabaseConfigurationError(ValueError):
    """Messages must not include a credential-bearing URL."""


class DatabaseSettings(ServiceSettings):
    db_schema: str
    migration_database_url: SecretStr | None = None
    db_pool_size: int = Field(default=2, ge=1, le=10)
    db_max_overflow: int = Field(default=1, ge=0, le=5)
    db_connect_timeout_seconds: float = Field(default=5, gt=0, le=30)
    db_pool_timeout_seconds: float = Field(default=5, gt=0, le=30)
    db_query_timeout_seconds: float = Field(default=5, gt=0, le=30)
    db_ssl_mode: Literal["disable", "require", "verify-full"] = "verify-full"
    db_ssl_ca_file: Path | None = None


def postgres_url(
    secret: SecretStr, expected_role: str | None = None, *, test_only: bool = False
) -> URL:
    try:
        url = make_url(secret.get_secret_value())
        if url.drivername not in {"postgres", "postgresql", "postgresql+asyncpg"}:
            raise ValueError
        if not url.host or not url.database or not url.username or url.query:
            raise ValueError
        if (test_only or os.getenv("APP_ENV") == "test") and (
            url.host not in {"127.0.0.1", "localhost", "::1"} or url.database != "commerce_test"
        ):
            raise ValueError
        # This base supports direct/session poolers only, not transaction pooling.
        if url.port == 6543:
            raise ValueError
        if expected_role and url.username.split(".", 1)[0] != expected_role:
            raise ValueError
        return url.set(drivername="postgresql+asyncpg")
    except (ValueError, TypeError, ArgumentError) as exc:
        raise DatabaseConfigurationError(
            "Use a PostgreSQL direct/session URL with the correct role and no query parameters"
        ) from exc


def ssl_context(
    mode: str, host: str | None, ca_file: str | Path | None = None
) -> ssl.SSLContext | bool:
    if mode == "disable":
        if host not in {"localhost", "127.0.0.1", "::1"}:
            raise DatabaseConfigurationError("SSL can only be disabled for loopback test databases")
        return False
    context = ssl.create_default_context()
    if ca_file:
        try:
            context.load_verify_locations(cafile=str(Path(ca_file).expanduser().resolve()))
        except (OSError, ssl.SSLError) as exc:
            raise DatabaseConfigurationError(
                "Cannot load database CA file; "
                "download the certificate from Supabase Database settings"
            ) from exc
    if mode == "require":
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


class Database:
    def __init__(self, settings: DatabaseSettings, spec: DatabaseSpec) -> None:
        if settings.db_schema != spec.schema:
            raise DatabaseConfigurationError("Configured schema does not belong to this service")
        if settings.database_url is None:
            raise DatabaseConfigurationError("Missing runtime database URL")
        url = postgres_url(
            settings.database_url, spec.runtime, test_only=settings.app_env == "test"
        )
        self.spec = spec
        self.engine = create_async_engine(
            url,
            echo=False,
            hide_parameters=True,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
            connect_args={
                "ssl": ssl_context(settings.db_ssl_mode, url.host, settings.db_ssl_ca_file),
                "timeout": settings.db_connect_timeout_seconds,
                "command_timeout": settings.db_query_timeout_seconds,
                "server_settings": {
                    "application_name": spec.service,
                    "search_path": f"{spec.schema},pg_catalog",
                },
            },
        )
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False, autoflush=False
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        # No implicit commit. The use case owns `async with session.begin()`.
        async with self.session_factory() as session:
            yield session

    async def readiness(self) -> str:
        try:
            async with self.engine.connect() as connection:
                row = (
                    await connection.execute(
                        text(
                            "SELECT current_user, current_schema(), "
                            "has_schema_privilege(current_user, :schema, 'USAGE'), "
                            "NOT has_schema_privilege(current_user, :schema, 'CREATE')"
                        ),
                        {"schema": self.spec.schema},
                    )
                ).one()
            if (
                row[0] != self.spec.runtime
                or row[1] != self.spec.schema
                or not row[2]
                or not row[3]
            ):
                return "permission_check_failed"
            return "ready"
        except Exception:
            # Never return or log driver exception text/URL to a health caller.
            return "unavailable"

    async def close(self) -> None:
        await self.engine.dispose()
