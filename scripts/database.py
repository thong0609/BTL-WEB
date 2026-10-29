"""Explicit database administration. No credentials are accepted on the command line."""

import argparse
import asyncio
import importlib
import json
import os
import ssl
from pathlib import Path
from time import monotonic

from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from commerce_backend_common.database import (
    DATABASE_SPECS,
    Database,
    DatabaseSettings,
    database_spec,
    postgres_url,
    ssl_context,
)
from commerce_backend_common.database_bootstrap import BootstrapBusyError, bootstrap

ROOT = Path(__file__).resolve().parents[1]


def bootstrap_target(target: str):
    name = "TEST_ADMIN_DATABASE_URL" if target == "test" else "BOOTSTRAP_DATABASE_URL"
    secret = SecretStr(os.environ[name])
    url = postgres_url(secret)
    if target == "test":
        if url.host not in {"127.0.0.1", "localhost", "::1"} or url.database != "commerce_test":
            raise ValueError("Test bootstrap only accepts loopback database commerce_test")
        mode = "disable"
    else:
        project = os.environ["SUPABASE_PROJECT_REF"]
        direct = url.host == f"db.{project}.supabase.co"
        session = bool(
            url.host
            and url.host.endswith(".pooler.supabase.com")
            and url.username
            and url.username.endswith(f".{project}")
        )
        if not project or url.database != "postgres" or not (direct or session):
            raise ValueError("Bootstrap target does not match the expected Supabase dev project")
        mode = os.getenv("BOOTSTRAP_SSL_MODE", "verify-full")
        if mode not in {"require", "verify-full"}:
            raise ValueError("Dev bootstrap requires SSL")
    return url, ssl_context(mode, url.host, os.getenv("BOOTSTRAP_SSL_CA_FILE"))


async def bootstrap_database(target: str) -> None:
    started = monotonic()

    def progress(message: str) -> None:
        print(f"[{monotonic() - started:.1f}s] {message}", flush=True)

    url, tls = bootstrap_target(target)
    timeout = int(os.getenv("BOOTSTRAP_TIMEOUT_SECONDS", "180"))
    if not 1 <= timeout <= 600:
        raise ValueError("BOOTSTRAP_TIMEOUT_SECONDS must be between 1 and 600")
    passwords = {
        role: os.environ[f"{role.upper()}_PASSWORD"]
        for spec in DATABASE_SPECS
        for role in (spec.runtime, spec.migrator)
    }
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={
            "ssl": tls,
            "timeout": 5,
            "command_timeout": 15,
            "server_settings": {"application_name": "commerce-bootstrap"},
        },
    )
    try:
        progress(f"Connecting to {target} database; overall timeout {timeout}s")
        async with asyncio.timeout(timeout):
            async with engine.begin() as connection:
                await bootstrap(connection, passwords, progress=progress)
    finally:
        await engine.dispose()
    progress("Bootstrap complete: 5 schemas, owner/migrator/runtime roles; no business tables")


async def inspect_database(settings: DatabaseSettings) -> None:
    spec = database_spec(settings.service_name)
    database = Database(settings, spec)
    try:
        if await database.readiness() != "ready":
            raise ValueError("Runtime connection or schema permission check failed")
        async with database.session() as session:
            for other in DATABASE_SPECS:
                if other == spec:
                    continue
                allowed = await session.scalar(
                    text(
                        "SELECT has_schema_privilege(current_user, :schema, 'USAGE') "
                        "OR has_schema_privilege(current_user, :schema, 'CREATE')"
                    ),
                    {"schema": other.schema},
                )
                if allowed:
                    raise ValueError("Runtime role has cross-service schema access")
            writable = await session.scalar(
                text("SELECT has_table_privilege(current_user, :table, 'UPDATE')"),
                {"table": f"{spec.schema}.alembic_version"},
            )
            if writable:
                raise ValueError("Runtime role can alter the migration version table")
    finally:
        await database.close()
    print(json.dumps({"service": spec.service, "schema": spec.schema, "runtimeAccess": "verified"}))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["bootstrap", "upgrade", "current", "check", "revision", "inspect"]
    )
    parser.add_argument("--service", choices=[spec.service for spec in DATABASE_SPECS])
    parser.add_argument("--target", choices=["dev", "test"], default="dev")
    parser.add_argument(
        "--apply", action="store_true", help="Explicitly allow bootstrap/migration writes"
    )
    parser.add_argument("--message", help="Revision description, never include secrets")
    args = parser.parse_args()
    if args.action in {"bootstrap", "upgrade", "revision"} and not args.apply:
        parser.error("This operation requires --apply")
    try:
        if args.action == "bootstrap":
            asyncio.run(bootstrap_database(args.target))
            return 0
        if not args.service:
            parser.error("--service is required")
        spec = database_spec(args.service)
        module = f"commerce_{spec.role_prefix}"
        settings: DatabaseSettings = importlib.import_module(f"{module}.settings").Settings()
        if args.action == "inspect":
            asyncio.run(inspect_database(settings))
            return 0
        config = Config(str(ROOT / "apps" / args.service / "alembic.ini"))
        if args.action == "upgrade":
            command.upgrade(config, "head")
        elif args.action == "current":
            command.current(config)
        elif args.action == "check":
            command.check(config)
        elif args.action == "revision":
            if not args.message:
                parser.error("revision requires --message")
            command.revision(config, message=args.message, autogenerate=True)
        print(f"{args.action} complete: {spec.service}")
        return 0
    except Exception as exc:
        # Do not print SQLAlchemy/Pydantic/Alembic exception strings: they may contain secrets.
        print(f"Database operation failed ({type(exc).__name__}); check configuration/permissions")
        if isinstance(exc, BootstrapBusyError):
            print("Another bootstrap is running. Wait for it to finish; do not start another copy.")
        elif isinstance(exc, TimeoutError):
            print(
                "Bootstrap did not confirm completion within its timeout; "
                "inspect its state before retrying."
            )
        if isinstance(exc, ssl.SSLCertVerificationError):
            print(
                "TLS certificate verification failed. Download the CA from Supabase Database "
                "settings and set BOOTSTRAP_SSL_CA_FILE (bootstrap) or DB_SSL_CA_FILE (service). "
                "Keep verify-full enabled."
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
