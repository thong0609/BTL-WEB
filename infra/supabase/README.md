# Shared-dev PostgreSQL bootstrap

Implementation: `commerce_backend_common.database_bootstrap`, invoked explicitly through `scripts/database.py`. No application imports or runs bootstrap during startup. There is no SQL file containing passwords.

1. Review target project and administrative permissions; prepare process environment listed in `bootstrap.env.example`. The template is not auto-loaded. Do not commit values or paste secrets into command-line arguments/logs.
2. From repository root, run `uv run --locked --all-packages python scripts/database.py bootstrap --target dev --apply` only against the intended dev project.
3. Configure the ignored `.env` for each owning service: runtime/migrator URLs, fixed schema and TLS settings.
4. Run that service's migration and read-only runtime inspection using the commands in [step 3](../../docs/development/SETUP-STEP-3.md).

Bootstrap creates owner (NOLOGIN), migrator (LOGIN, NOINHERIT, member of owner), runtime (LOGIN, NOINHERIT) for each of 5 schemas. It grants the bootstrap administrator membership in owner roles so managed PostgreSQL can administer them. No Supabase-managed schema/role is dropped or altered globally. Existing service roles/schema owners with conflicting privileges are rejected rather than silently repurposed.

All migration DDL runs after SET ROLE to the owning role; default privileges are configured for that owner, not just the login migrator. Runtime receives SELECT/INSERT/UPDATE/DELETE and sequence USAGE/SELECT in its own schema, not TRUNCATE or DDL. Alembic version table privileges are revoked separately after migration. Bootstrap also revokes existing cross-service grants and direct access by common Data API roles on these application objects.

Before applying on Supabase, check that commerce_* schemas are not exposed in Data API settings. SQL schema grants do not replace this project configuration review. The test database does not emulate Supabase-specific role limitations or pooler/TLS behavior.

Bootstrap reruns are explicit administrative operations and reapply the supplied passwords. Update service secrets in coordination; do not run it casually while the team is connected. No project, cloud connection or credentials have been provisioned by this setup step.

If certificate verification fails, download the trusted CA from Supabase Database settings. Set BOOTSTRAP_SSL_CA_FILE for bootstrap and DB_SSL_CA_FILE for each service's runtime/migrations; keep verify-full. See [TLS troubleshooting](../../docs/development/SETUP-STEP-3.md#9-xử-lý-sslcertverificationerror). The local certs directory is ignored by Git.
