"""Identity schema mapping, constraints, migration roles, and rotation locking."""

import asyncio
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable

from commerce_identity.db import SPEC, Base
from commerce_identity.models import RefreshSession, User, UserIdentity


def test_identity_mapping_compiles_for_postgresql():
    configure_mappers()
    tables = Base.metadata.sorted_tables
    assert {table.name for table in tables} == {"users", "refresh_sessions", "user_identities"}
    dialect = postgresql.dialect()
    for table in tables:
        assert table.schema == SPEC.schema
        assert str(CreateTable(table).compile(dialect=dialect))
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table.schema == SPEC.schema
        for index in table.indexes:
            assert str(CreateIndex(index).compile(dialect=dialect))


@pytest.mark.integration
def test_identity_constraints_and_family_delete(postgres_test):
    async def exercise():
        engine = create_async_engine(postgres_test["admin_url"])
        now = datetime.now(UTC)
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    await connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SPEC.schema}"))
                    await connection.run_sync(Base.metadata.create_all)

                    async def invalid(statement, expected, error=IntegrityError):
                        with pytest.raises(error) as info:
                            async with connection.begin_nested():
                                await connection.execute(statement)
                        assert expected in str(info.value.orig)

                    async def insert_user(**overrides):
                        values = {
                            "email": f"{uuid4()}@example.test",
                            "full_name": "Test",
                            "role": "CUSTOMER",
                            "status": "ACTIVE",
                            "password_hash": None,
                        }
                        values.update(overrides)
                        return await connection.scalar(
                            User.__table__.insert().values(**values).returning(User.id)
                        )

                    user_id = await insert_user()
                    duplicate_email = f"{uuid4()}@example.test"
                    await insert_user(email=duplicate_email)
                    await invalid(
                        User.__table__.insert().values(
                            email=duplicate_email,
                            full_name="x",
                            role="CUSTOMER",
                            status="ACTIVE",
                        ),
                        "uq_users_email",
                    )
                    for field, value, expected in (
                        ("role", "OTHER", "ck_users_role_valid"),
                        ("status", "OTHER", "ck_users_status_valid"),
                    ):
                        values = {
                            "email": f"{uuid4()}@example.test",
                            "full_name": "x",
                            "role": "CUSTOMER",
                            "status": "ACTIVE",
                        }
                        values[field] = value
                        await invalid(User.__table__.insert().values(**values), expected)

                    def session_values(owner=user_id, **overrides):
                        values = {
                            "user_id": owner,
                            "family_id": uuid4(),
                            "token_hash": uuid4().hex + uuid4().hex,
                            "expires_at": now + timedelta(hours=1),
                            "family_expires_at": now + timedelta(days=1),
                        }
                        values.update(overrides)
                        return values

                    family, old_id, new_id = uuid4(), uuid4(), uuid4()
                    hash1 = uuid4().hex + uuid4().hex
                    hash2 = uuid4().hex + uuid4().hex
                    await connection.execute(
                        RefreshSession.__table__.insert().values(
                            **session_values(family_id=family, id=old_id, token_hash=hash1)
                        )
                    )
                    await invalid(
                        RefreshSession.__table__.insert().values(
                            **session_values(family_id=family, token_hash=hash2)
                        ),
                        "uq_refresh_sessions_one_unrevoked_per_family",
                    )
                    for malformed in ("A" * 64, "a" * 63, "g" * 64):
                        await invalid(
                            RefreshSession.__table__.insert().values(
                                **session_values(token_hash=malformed)
                            ),
                            "ck_refresh_sessions_token_hash_format",
                        )
                    await invalid(
                        RefreshSession.__table__.insert().values(
                            **session_values(token_hash="a" * 65)
                        ),
                        "value too long",
                        DBAPIError,
                    )
                    await invalid(
                        RefreshSession.__table__.insert().values(
                            **session_values(token_hash=hash1)
                        ),
                        "uq_refresh_sessions_token_hash",
                    )
                    await invalid(
                        RefreshSession.__table__.insert().values(
                            **session_values(expires_at=now + timedelta(days=2))
                        ),
                        "ck_refresh_sessions_expires_within_family",
                    )
                    await invalid(
                        RefreshSession.__table__.insert().values(
                            **session_values(replaced_by_id=old_id)
                        ),
                        "ck_refresh_sessions_replaced_requires_revoked",
                    )
                    await invalid(
                        RefreshSession.__table__.insert().values(
                            **session_values(id=new_id, replaced_by_id=new_id, revoked_at=now)
                        ),
                        "ck_refresh_sessions_not_self_replaced",
                    )
                    await invalid(
                        User.__table__.delete().where(User.id == user_id),
                        "fk_refresh_sessions_user_id_users",
                    )

                    await connection.execute(
                        RefreshSession.__table__.update()
                        .where(RefreshSession.id == old_id)
                        .values(revoked_at=now)
                    )
                    await connection.execute(
                        RefreshSession.__table__.insert().values(
                            **session_values(family_id=family, id=new_id, token_hash=hash2)
                        )
                    )
                    await connection.execute(
                        RefreshSession.__table__.update()
                        .where(RefreshSession.id == old_id)
                        .values(replaced_by_id=new_id)
                    )
                    result = await connection.execute(
                        RefreshSession.__table__.delete().where(RefreshSession.family_id == family)
                    )
                    assert result.rowcount == 2

                    u2, u3 = await insert_user(), await insert_user()
                    await connection.execute(
                        UserIdentity.__table__.insert().values(
                            user_id=u2,
                            provider="GOOGLE",
                            provider_subject="subject-1",
                            provider_email=None,
                        )
                    )
                    await invalid(
                        UserIdentity.__table__.insert().values(
                            user_id=u3, provider="GOOGLE", provider_subject="subject-1"
                        ),
                        "uq_user_identities_provider_provider_subject",
                    )
                    await invalid(
                        UserIdentity.__table__.insert().values(
                            user_id=u2, provider="GOOGLE", provider_subject="subject-2"
                        ),
                        "uq_user_identities_user_id_provider",
                    )
                    await invalid(
                        UserIdentity.__table__.insert().values(
                            user_id=u3, provider="OTHER", provider_subject="subject-3"
                        ),
                        "ck_user_identities_provider_valid",
                    )
                    await invalid(
                        User.__table__.delete().where(User.id == u2),
                        "fk_user_identities_user_id_users",
                    )
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(exercise())


@pytest.mark.integration
def test_identity_runtime_migration_and_rotation(postgres_test):
    password = quote(postgres_test["password"], safe="")
    port = postgres_test["port"]
    runtime_url = f"postgresql+asyncpg://identity_runtime:{password}@127.0.0.1:{port}/commerce_test"
    env = {
        **postgres_test["env"],
        "DB_SSL_MODE": "disable",
        "SERVICE_NAME": "identity-service",
        "DB_SCHEMA": SPEC.schema,
        "DATABASE_URL": runtime_url,
        "MIGRATION_DATABASE_URL": (
            f"postgresql://identity_migrator:{password}@127.0.0.1:{port}/commerce_test"
        ),
    }
    for args in (
        ["bootstrap", "--target", "test", "--apply"],
        ["upgrade", "--service", "identity-service", "--apply"],
        ["check", "--service", "identity-service"],
    ):
        result = subprocess.run(
            [sys.executable, "scripts/database.py", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    async def exercise():
        admin = create_async_engine(postgres_test["admin_url"])
        runtime = create_async_engine(runtime_url)

        EXPECTED = (
            (
                "users",
                "pk_users",
                set(),
                {"uq_users_email"},
                {"ck_users_role_valid", "ck_users_status_valid"},
                set(),
            ),
            (
                "refresh_sessions",
                "pk_refresh_sessions",
                {
                    "fk_refresh_sessions_user_id_users",
                    "fk_refresh_sessions_replaced_by_id_refresh_sessions",
                },
                {"uq_refresh_sessions_token_hash"},
                {
                    "ck_refresh_sessions_token_hash_format",
                    "ck_refresh_sessions_expires_within_family",
                    "ck_refresh_sessions_replaced_requires_revoked",
                    "ck_refresh_sessions_not_self_replaced",
                },
                {
                    "uq_refresh_sessions_one_unrevoked_per_family",
                    "ix_refresh_sessions_user_id_revoked_at",
                    "ix_refresh_sessions_family_expires_at",
                },
            ),
            (
                "user_identities",
                "pk_user_identities",
                {"fk_user_identities_user_id_users"},
                {
                    "uq_user_identities_provider_provider_subject",
                    "uq_user_identities_user_id_provider",
                },
                {"ck_user_identities_provider_valid"},
                set(),
            ),
        )

        def check_schema(sync_conn):
            inspector = inspect(sync_conn)
            names = inspector.get_table_names(schema=SPEC.schema)
            assert set(names) == {
                "alembic_version",
                "users",
                "refresh_sessions",
                "user_identities",
            }
            for table, pk, fks, uniques, checks, indexes in EXPECTED:
                assert inspector.get_pk_constraint(table, schema=SPEC.schema)["name"] == pk
                assert {
                    item["name"] for item in inspector.get_foreign_keys(table, schema=SPEC.schema)
                } == fks
                assert {
                    item["name"]
                    for item in inspector.get_unique_constraints(table, schema=SPEC.schema)
                } == uniques
                assert {
                    item["name"]
                    for item in inspector.get_check_constraints(table, schema=SPEC.schema)
                } == checks
                assert {
                    item["name"]
                    for item in inspector.get_indexes(table, schema=SPEC.schema)
                    if "duplicates_constraint" not in item
                } == indexes
            partial = next(
                item
                for item in inspector.get_indexes("refresh_sessions", schema=SPEC.schema)
                if item["name"] == "uq_refresh_sessions_one_unrevoked_per_family"
            )
            assert partial["unique"] is True
            assert "revoked_at IS NULL" in partial["dialect_options"]["postgresql_where"]

        try:
            async with admin.connect() as conn:
                await conn.run_sync(check_schema)

            async with runtime.begin() as conn:
                uid = uuid4()
                await conn.execute(
                    text(
                        "INSERT INTO commerce_identity.users "
                        "(id,email,full_name,role,status) "
                        "VALUES (:id,:email,'Test','CUSTOMER','ACTIVE')"
                    ),
                    {"id": uid, "email": f"{uuid4()}@example.test"},
                )
                await conn.execute(
                    text("SELECT id FROM commerce_identity.users WHERE id=:id FOR UPDATE"),
                    {"id": uid},
                )
                await conn.execute(
                    text("UPDATE commerce_identity.users SET full_name='Changed' WHERE id=:id"),
                    {"id": uid},
                )
                await conn.execute(
                    text("DELETE FROM commerce_identity.users WHERE id=:id"), {"id": uid}
                )
                with pytest.raises(ProgrammingError) as info:
                    await conn.execute(
                        text("CREATE TABLE commerce_identity.runtime_forbidden (id int)")
                    )
                assert "permission denied" in str(info.value.orig)

            token_hash = uuid4().hex + uuid4().hex
            family_id, owner_id = uuid4(), uuid4()
            async with admin.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO commerce_identity.users "
                        "(id,email,full_name,role,status) "
                        "VALUES (:id,:email,'Race','CUSTOMER','ACTIVE')"
                    ),
                    {"id": owner_id, "email": f"{uuid4()}@example.test"},
                )
                await conn.execute(
                    text(
                        "INSERT INTO commerce_identity.refresh_sessions "
                        "(id,user_id,family_id,token_hash,expires_at,family_expires_at) "
                        "VALUES (:id,:uid,:family,:hash,now()+interval '1 hour',"
                        "now()+interval '1 day')"
                    ),
                    {
                        "id": uuid4(),
                        "uid": owner_id,
                        "family": family_id,
                        "hash": token_hash,
                    },
                )

            conn1 = await runtime.connect()
            conn2 = await runtime.connect()
            tx1 = await conn1.begin()
            tx2 = await conn2.begin()
            try:
                await conn1.execute(
                    text(
                        "SELECT id FROM commerce_identity.refresh_sessions "
                        "WHERE token_hash=:hash FOR UPDATE"
                    ),
                    {"hash": token_hash},
                )
                waiter = asyncio.create_task(
                    conn2.execute(
                        text(
                            "SELECT id FROM commerce_identity.refresh_sessions "
                            "WHERE token_hash=:hash FOR UPDATE"
                        ),
                        {"hash": token_hash},
                    )
                )
                await asyncio.sleep(0.2)
                assert not waiter.done()
                await tx1.commit()
                await waiter
                await tx2.commit()
            finally:
                if tx1.is_active:
                    await tx1.rollback()
                if tx2.is_active:
                    await tx2.rollback()
                await conn1.close()
                await conn2.close()

            async with admin.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE commerce_identity.refresh_sessions "
                        "SET revoked_at = now() WHERE token_hash = :hash"
                    ),
                    {"hash": token_hash},
                )

            async def competing_insert():
                async with runtime.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO commerce_identity.refresh_sessions "
                            "(id,user_id,family_id,token_hash,expires_at,family_expires_at) "
                            "VALUES (:id,:uid,:family,:hash,now()+interval '1 hour',"
                            "now()+interval '1 day')"
                        ),
                        {
                            "id": uuid4(),
                            "uid": owner_id,
                            "family": family_id,
                            "hash": uuid4().hex + uuid4().hex,
                        },
                    )

            outcomes = await asyncio.gather(
                competing_insert(), competing_insert(), return_exceptions=True
            )
            failures = [item for item in outcomes if isinstance(item, IntegrityError)]
            assert len(failures) == 1
            assert "uq_refresh_sessions_one_unrevoked_per_family" in str(failures[0].orig)
        finally:
            await runtime.dispose()
            await admin.dispose()

    asyncio.run(exercise())
