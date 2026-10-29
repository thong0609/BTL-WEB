"""Explicit schema/role bootstrap. Never imported or run by an API startup."""

import re
from collections.abc import Callable, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from commerce_backend_common.database import DATABASE_SPECS


def identifier(name: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
        raise ValueError("Invalid administrative identifier")
    return f'"{name}"'


def password_literal(value: str) -> str:
    if len(value) < 16 or "\x00" in value:
        raise ValueError("Bootstrap passwords must contain at least 16 characters")
    return "'" + value.replace("'", "''") + "'"


class BootstrapBusyError(RuntimeError):
    """Another instance of this bootstrap already owns the transaction lock."""


async def bootstrap(
    connection: AsyncConnection,
    passwords: Mapping[str, str],
    progress: Callable[[str], None] | None = None,
) -> None:
    """Run inside one transaction with an explicitly provided administrative connection."""
    locked = await connection.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtext('commerce:bootstrap'))")
    )
    if not locked:
        raise BootstrapBusyError("Another bootstrap is already running")
    await connection.execute(text("SET LOCAL lock_timeout='10s'"))
    await connection.execute(text("SET LOCAL standard_conforming_strings=on"))
    admin = str(await connection.scalar(text("SELECT current_user")))
    admin_q = identifier(admin)
    db_name = str(await connection.scalar(text("SELECT current_database()")))
    db_q = identifier(db_name)
    for index, spec in enumerate(DATABASE_SPECS, start=1):
        if progress:
            progress(f"Preparing schema {index}/{len(DATABASE_SPECS)}: {spec.schema}")
        owner, migrator, runtime = map(identifier, (spec.owner, spec.migrator, spec.runtime))
        schema = identifier(spec.schema)
        for role, login in ((spec.owner, False), (spec.migrator, True), (spec.runtime, True)):
            row = (
                await connection.execute(
                    text(
                        "SELECT rolsuper, rolcreatedb, rolcreaterole, "
                        "rolbypassrls, rolinherit, rolcanlogin "
                        "FROM pg_roles WHERE rolname=:role"
                    ),
                    {"role": role},
                )
            ).first()
            if row is not None:
                if any(row[:5]) or bool(row[5]) != login:
                    raise ValueError("Existing service role has unexpected privileges")
            else:
                await connection.execute(
                    text(
                        f"CREATE ROLE {identifier(role)} {'LOGIN' if login else 'NOLOGIN'} "
                        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
                    )
                )
            if login:
                # Administrative statements must not be logged; callers suppress raw exceptions.
                await connection.exec_driver_sql(
                    f"ALTER ROLE {identifier(role)} PASSWORD {password_literal(passwords[role])}"
                )
        for role, allowed in ((spec.runtime, set()), (spec.migrator, {spec.owner})):
            memberships: set[str] = set(
                (
                    await connection.execute(
                        text(
                            "SELECT parent.rolname FROM pg_auth_members m "
                            "JOIN pg_roles parent ON parent.oid=m.roleid "
                            "JOIN pg_roles child ON child.oid=m.member WHERE child.rolname=:role"
                        ),
                        {"role": role},
                    )
                ).scalars()
            )
            if memberships - allowed:
                raise ValueError("Existing service role has unexpected memberships")
        await connection.execute(text(f"GRANT {owner} TO {migrator}"))
        # Needed for SET ROLE / ALTER DEFAULT PRIVILEGES on managed PostgreSQL too.
        await connection.execute(text(f"GRANT {owner} TO {admin_q}"))
        existing_owner = await connection.scalar(
            text("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname=:schema"),
            {"schema": spec.schema},
        )
        if existing_owner is not None and existing_owner != spec.owner:
            raise ValueError("Existing service schema has an unexpected owner")
        await connection.execute(
            text(f"CREATE SCHEMA IF NOT EXISTS {schema} AUTHORIZATION {owner}")
        )
        await connection.execute(text(f"REVOKE ALL ON SCHEMA {schema} FROM PUBLIC"))
        await connection.execute(text(f"REVOKE ALL ON SCHEMA {schema} FROM {runtime}, {migrator}"))
        for exposed_role in ("anon", "authenticated", "service_role"):
            exists = await connection.scalar(
                text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:name)"),
                {"name": exposed_role},
            )
            if exists:
                await connection.execute(
                    text(f"REVOKE ALL ON SCHEMA {schema} FROM {identifier(exposed_role)}")
                )
                await connection.execute(
                    text(
                        f"REVOKE ALL ON ALL TABLES IN SCHEMA {schema} "
                        f"FROM {identifier(exposed_role)}"
                    )
                )
                await connection.execute(
                    text(
                        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {schema} "
                        f"FROM {identifier(exposed_role)}"
                    )
                )
        await connection.execute(text(f"GRANT CONNECT ON DATABASE {db_q} TO {runtime}, {migrator}"))
        await connection.execute(text(f"GRANT USAGE ON SCHEMA {schema} TO {runtime}"))
        await connection.execute(
            text(f"REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM {runtime}")
        )
        await connection.execute(
            text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {schema} FROM {runtime}")
        )
        await connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM PUBLIC"))
        await connection.execute(
            text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {schema} FROM PUBLIC")
        )
        await connection.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} "
                f"TO {runtime}"
            )
        )
        await connection.execute(
            text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {runtime}")
        )
        await connection.execute(text(f"SET LOCAL ROLE {owner}"))
        await connection.execute(
            text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON TABLES FROM PUBLIC")
        )
        await connection.execute(
            text(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {runtime}"
            )
        )
        await connection.execute(
            text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON SEQUENCES FROM PUBLIC")
        )
        await connection.execute(
            text(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} "
                f"GRANT USAGE, SELECT ON SEQUENCES TO {runtime}"
            )
        )
        await connection.execute(
            text(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} "
                f"REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
            )
        )
        version_table = await connection.scalar(
            text("SELECT to_regclass(:name)"), {"name": f"{spec.schema}.alembic_version"}
        )
        if version_table:
            await connection.execute(text(f"REVOKE ALL ON {schema}.alembic_version FROM {runtime}"))
        await connection.execute(text("RESET ROLE"))
    # Existing accidental cross-service grants must not survive a bootstrap rerun.
    for own in DATABASE_SPECS:
        if progress:
            progress(f"Restricting cross-service access: {own.schema}")
        # PostgreSQL accepts multiple grantees in one REVOKE. This preserves the
        # same restrictions while cutting cloud round trips from 180 to 15.
        grantees = ", ".join(
            identifier(role)
            for other in DATABASE_SPECS
            if own != other
            for role in (other.runtime, other.migrator, other.owner)
        )
        schema = identifier(own.schema)
        for object_clause in (
            f"SCHEMA {schema}",
            f"ALL TABLES IN SCHEMA {schema}",
            f"ALL SEQUENCES IN SCHEMA {schema}",
        ):
            await connection.execute(text(f"REVOKE ALL ON {object_clause} FROM {grantees}"))
    if progress:
        progress("All permissions prepared; committing transaction")
