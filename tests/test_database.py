import asyncio
import importlib
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from commerce_backend_common.database import (
    DATABASE_SPECS,
    Database,
    DatabaseConfigurationError,
    database_spec,
    postgres_url,
    ssl_context,
)
from commerce_backend_common.database_bootstrap import BootstrapBusyError, bootstrap

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_bootstrap_batches_revokes_and_rejects_concurrent_runs(postgres_test):
    from sqlalchemy import event

    async def exercise():
        engine = create_async_engine(
            postgres_test["admin_url"], poolclass=NullPool, connect_args={"ssl": False}
        )
        grouped = []

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def record_groups(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("REVOKE ALL ON") and " FROM " in statement:
                grantees = statement.split(" FROM ", 1)[1].split(", ")
                if len(grantees) == 12:
                    grouped.append(statement)

        passwords = {
            role: postgres_test["password"]
            for spec in DATABASE_SPECS
            for role in (spec.runtime, spec.migrator)
        }
        try:
            messages = []
            async with engine.begin() as connection:
                await bootstrap(connection, passwords, progress=messages.append)
            assert len(grouped) == 15
            assert len([m for m in messages if m.startswith("Preparing schema")]) == 5
            assert "committing transaction" in messages[-1]
            assert postgres_test["password"] not in " ".join(messages)
            async with engine.begin() as blocker:
                await blocker.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext('commerce:bootstrap'))")
                )
                async with engine.begin() as contender:
                    with pytest.raises(BootstrapBusyError):
                        await bootstrap(contender, passwords)
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def command(*arguments, env):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/database.py"), *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout
    return result


@pytest.mark.parametrize("service", [s.service for s in DATABASE_SPECS])
def test_schema_settings_are_fixed(service):
    spec = database_spec(service)
    cls = importlib.import_module(f"commerce_{spec.role_prefix}.settings").Settings
    assert cls(_env_file=None).db_schema == spec.schema
    for values in ({"db_schema": "public"}, {"db_pool_size": 0}, {"db_ssl_mode": "invalid"}):
        with pytest.raises(ValidationError):
            cls(_env_file=None, **values)


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///test.db",
        "not-a-url",
        "postgresql://postgres:secret@localhost/postgres",
        "postgresql://catalog_runtime:secret@localhost:6543/postgres",
        "postgresql://catalog_runtime:secret@localhost/postgres?sslmode=require",
    ],
)
def test_url_validation_does_not_echo_secrets(url):
    with pytest.raises(DatabaseConfigurationError) as failure:
        postgres_url(SecretStr(url), "catalog_runtime")
    assert "secret" not in str(failure.value)


def test_ssl_disable_is_loopback_only():
    assert ssl_context("disable", "127.0.0.1") is False
    with pytest.raises(DatabaseConfigurationError):
        ssl_context("disable", "db.example.supabase.co")


def test_unreachable_db_readiness_is_private():
    from commerce_catalog.main import create_app
    from commerce_catalog.settings import Settings

    config = Settings(
        _env_file=None,
        database_enabled=True,
        db_ssl_mode="disable",
        database_url="postgresql://catalog_runtime:secret@127.0.0.1:1/commerce_test",
        db_connect_timeout_seconds=0.2,
    )
    with TestClient(create_app(config)) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["checks"]["database"] == "unavailable"
        assert "secret" not in response.text


def test_bootstrap_requires_apply_and_safe_test_target():
    env = os.environ.copy()
    result = subprocess.run(
        [sys.executable, "scripts/database.py", "bootstrap", "--target", "test"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    env["TEST_ADMIN_DATABASE_URL"] = "postgresql://postgres:secret@db.remote.example/postgres"
    result = subprocess.run(
        [sys.executable, "scripts/database.py", "bootstrap", "--target", "test", "--apply"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "secret" not in result.stdout + result.stderr


def test_autogenerate_filters_and_rejects_foreign_metadata():
    from sqlalchemy import Column, Integer, MetaData, Table

    from commerce_backend_common.migrations import migration_options

    spec = database_spec("catalog-service")
    options = migration_options(spec, MetaData(schema=spec.schema))
    include = options["include_name"]
    assert include(spec.schema, "schema", {})
    assert not include(None, "schema", {})
    assert not include("auth", "schema", {})
    assert not include("products", "table", {"schema_name": "commerce_identity"})
    invalid = MetaData()
    Table("outside", invalid, Column("id", Integer), schema="commerce_identity")
    with pytest.raises(DatabaseConfigurationError):
        migration_options(spec, invalid)


def test_migration_has_no_runtime_url_fallback():
    env = os.environ.copy()
    env.pop("MIGRATION_DATABASE_URL", None)
    env["DATABASE_URL"] = "postgresql://catalog_runtime:secret@127.0.0.1/commerce_test"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/database.py",
            "upgrade",
            "--service",
            "catalog-service",
            "--apply",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "secret" not in result.stdout + result.stderr


def test_offline_migration_output_has_schema_and_no_credentials():
    env = os.environ.copy()
    env["MIGRATION_DATABASE_URL"] = "postgresql://catalog_migrator:secret@127.0.0.1/commerce_test"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "apps/catalog-service/alembic.ini",
            "upgrade",
            "head",
            "--sql",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "secret" not in result.stdout + result.stderr
    assert "commerce_catalog.alembic_version" in result.stdout


@pytest.mark.integration
def test_postgres_bootstrap_migrations_and_runtime_isolation(postgres_test):
    env = postgres_test["env"]
    password = quote(postgres_test["password"], safe="")
    port = postgres_test["port"]
    command("bootstrap", "--target", "test", "--apply", env=env)
    command("bootstrap", "--target", "test", "--apply", env=env)  # safe rerun
    for spec in DATABASE_SPECS:
        service_env = dict(env)
        service_env.update(
            DB_SSL_MODE="disable",
            SERVICE_NAME=spec.service,
            DB_SCHEMA=spec.schema,
            DATABASE_URL=f"postgresql://{spec.runtime}:{password}@127.0.0.1:{port}/commerce_test",
            MIGRATION_DATABASE_URL=(
                f"postgresql://{spec.migrator}:{password}@127.0.0.1:{port}/commerce_test"
            ),
        )
        command("upgrade", "--service", spec.service, "--apply", env=service_env)
        command("upgrade", "--service", spec.service, "--apply", env=service_env)
        command("current", "--service", spec.service, env=service_env)
        command("inspect", "--service", spec.service, env=service_env)
        command("check", "--service", spec.service, env=service_env)

    async def exercise():
        admin = create_async_engine(
            postgres_test["admin_url"], poolclass=NullPool, connect_args={"ssl": False}
        )
        try:
            async with admin.connect() as connection:
                tables = (
                    await connection.execute(
                        text(
                            "SELECT table_schema, table_name FROM information_schema.tables "
                            "WHERE table_schema LIKE 'commerce_%'"
                        )
                    )
                ).all()
                assert set(tables) == {(s.schema, "alembic_version") for s in DATABASE_SPECS}
            # Autogenerate must ignore actual tables outside the service, not just version tables.
            async with admin.begin() as connection:
                await connection.execute(text("CREATE TABLE public.unrelated_probe (id integer)"))
                await connection.execute(
                    text("CREATE TABLE commerce_identity.foreign_probe (id integer)")
                )
            catalog_env = dict(env)
            catalog_env.update(
                SERVICE_NAME="catalog-service",
                DB_SCHEMA="commerce_catalog",
                DB_SSL_MODE="disable",
                MIGRATION_DATABASE_URL=(
                    f"postgresql://catalog_migrator:{password}@127.0.0.1:{port}/commerce_test"
                ),
            )
            command("check", "--service", "catalog-service", env=catalog_env)
            async with admin.begin() as connection:
                assert await connection.scalar(
                    text(
                        "SELECT to_regclass('public.unrelated_probe') IS NOT NULL "
                        "AND to_regclass('commerce_identity.foreign_probe') IS NOT NULL"
                    )
                )
                await connection.execute(text("DROP TABLE public.unrelated_probe"))
                await connection.execute(text("DROP TABLE commerce_identity.foreign_probe"))
            for spec in DATABASE_SPECS:
                settings_cls = importlib.import_module(
                    f"commerce_{spec.role_prefix}.settings"
                ).Settings
                settings = settings_cls(
                    _env_file=None,
                    db_ssl_mode="disable",
                    database_enabled=True,
                    database_url=f"postgresql://{spec.runtime}:{password}@127.0.0.1:{port}/commerce_test",
                )
                db = Database(settings, spec)
                assert await db.readiness() == "ready"
                # Probes live only inside this disposable test DB and are removed below.
                migrator = create_async_engine(
                    f"postgresql+asyncpg://{spec.migrator}:{password}@127.0.0.1:{port}/commerce_test",
                    poolclass=NullPool,
                    connect_args={"ssl": False},
                )
                try:
                    async with migrator.begin() as connection:
                        await connection.execute(text(f'SET LOCAL ROLE "{spec.owner}"'))
                        await connection.execute(
                            text(
                                f'CREATE TABLE "{spec.schema}".setup_probe '
                                "(id integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY)"
                            )
                        )
                    async with db.session() as session:
                        async with session.begin():
                            await session.execute(
                                text(f'INSERT INTO "{spec.schema}".setup_probe DEFAULT VALUES')
                            )
                    async with db.session() as session:
                        assert (
                            await session.scalar(
                                text(f'SELECT count(*) FROM "{spec.schema}".setup_probe')
                            )
                            == 1
                        )
                    with pytest.raises(RuntimeError):
                        async with db.session() as session:
                            async with session.begin():
                                await session.execute(
                                    text(f'INSERT INTO "{spec.schema}".setup_probe VALUES (2)')
                                )
                                raise RuntimeError("force rollback")
                    async with db.session() as a, db.session() as b:
                        assert a is not b
                        assert (
                            await a.scalar(
                                text(f'SELECT count(*) FROM "{spec.schema}".setup_probe')
                            )
                            == 1
                        )

                    async def read_pid(database):
                        async with database.session() as session:
                            async with session.begin():
                                pid = await session.scalar(text("SELECT pg_backend_pid()"))
                                await session.execute(text("SELECT pg_sleep(0.1)"))
                                return pid

                    pids = await asyncio.gather(read_pid(db), read_pid(db))
                    assert pids[0] != pids[1]
                    forbidden = [
                        f'SET ROLE "{spec.owner}"',
                        f'CREATE TABLE "{spec.schema}".forbidden (id int)',
                        f'UPDATE "{spec.schema}".alembic_version SET version_num=version_num',
                        f'TRUNCATE "{spec.schema}".setup_probe',
                    ]
                    other = next(s for s in DATABASE_SPECS if s != spec)
                    forbidden.append(f'SELECT * FROM "{other.schema}".alembic_version')
                    from sqlalchemy.exc import DBAPIError

                    for statement in forbidden:
                        with pytest.raises(DBAPIError):
                            async with db.session() as session:
                                async with session.begin():
                                    await session.execute(text(statement))
                finally:
                    async with migrator.begin() as connection:
                        await connection.execute(text(f'SET LOCAL ROLE "{spec.owner}"'))
                        await connection.execute(
                            text(f'DROP TABLE IF EXISTS "{spec.schema}".setup_probe')
                        )
                    await migrator.dispose()
                    await db.close()
        finally:
            await admin.dispose()

    asyncio.run(exercise())

    # Actual FastAPI lifespan and session dependency against the disposable PostgreSQL.
    from typing import Annotated

    from fastapi import Depends
    from sqlalchemy.ext.asyncio import AsyncSession

    from commerce_backend_common.database_lifespan import get_session
    from commerce_catalog.main import create_app
    from commerce_catalog.settings import Settings

    app = create_app(
        Settings(
            _env_file=None,
            database_enabled=True,
            db_ssl_mode="disable",
            database_url=f"postgresql://catalog_runtime:{password}@127.0.0.1:{port}/commerce_test",
        )
    )

    @app.get("/test-session")
    async def session_probe(session: Annotated[AsyncSession, Depends(get_session)]):
        return {"role": await session.scalar(text("SELECT current_user"))}

    with TestClient(app) as client:
        assert client.get("/health/ready").json()["checks"]["database"] == "ready"
        assert client.get("/test-session").json() == {"role": "catalog_runtime"}
    assert app.state.database is None
