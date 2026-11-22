"""Create the Identity authentication schema."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_identity_auth_schema"
down_revision = "0001_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('CUSTOMER','ADMIN')", name=op.f("ck_users_role_valid")),
        sa.CheckConstraint("status IN ('ACTIVE','DISABLED')", name=op.f("ck_users_status_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        schema="commerce_identity",
    )
    op.create_table(
        "refresh_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("family_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_refresh_sessions_token_hash_format")
        ),
        sa.CheckConstraint(
            "expires_at <= family_expires_at",
            name=op.f("ck_refresh_sessions_expires_within_family"),
        ),
        sa.CheckConstraint(
            "replaced_by_id IS NULL OR revoked_at IS NOT NULL",
            name=op.f("ck_refresh_sessions_replaced_requires_revoked"),
        ),
        sa.CheckConstraint(
            "replaced_by_id IS NULL OR replaced_by_id <> id",
            name=op.f("ck_refresh_sessions_not_self_replaced"),
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["commerce_identity.refresh_sessions.id"],
            name=op.f("fk_refresh_sessions_replaced_by_id_refresh_sessions"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["commerce_identity.users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_refresh_sessions_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_sessions_token_hash")),
        schema="commerce_identity",
    )
    op.create_index(
        "uq_refresh_sessions_one_unrevoked_per_family",
        "refresh_sessions",
        ["family_id"],
        unique=True,
        schema="commerce_identity",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_refresh_sessions_user_id_revoked_at",
        "refresh_sessions",
        ["user_id", "revoked_at"],
        schema="commerce_identity",
    )
    op.create_index(
        "ix_refresh_sessions_family_expires_at",
        "refresh_sessions",
        ["family_expires_at"],
        schema="commerce_identity",
    )
    op.create_table(
        "user_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("provider_subject", sa.String(255), nullable=False),
        sa.Column("provider_email", sa.String(254), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "provider IN ('GOOGLE')", name=op.f("ck_user_identities_provider_valid")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["commerce_identity.users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_user_identities_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_identities")),
        sa.UniqueConstraint(
            "provider",
            "provider_subject",
            name=op.f("uq_user_identities_provider_provider_subject"),
        ),
        sa.UniqueConstraint(
            "user_id", "provider", name=op.f("uq_user_identities_user_id_provider")
        ),
        schema="commerce_identity",
    )


def downgrade() -> None:
    op.drop_table("user_identities", schema="commerce_identity")
    op.drop_index(
        "ix_refresh_sessions_family_expires_at",
        table_name="refresh_sessions",
        schema="commerce_identity",
    )
    op.drop_index(
        "ix_refresh_sessions_user_id_revoked_at",
        table_name="refresh_sessions",
        schema="commerce_identity",
    )
    op.drop_index(
        "uq_refresh_sessions_one_unrevoked_per_family",
        table_name="refresh_sessions",
        schema="commerce_identity",
    )
    op.drop_table("refresh_sessions", schema="commerce_identity")
    op.drop_table("users", schema="commerce_identity")
