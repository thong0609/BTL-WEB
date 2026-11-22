"""Keep validated action input for audit without inventing status changes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_action_audit"
down_revision = "0002_order_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "order_action_requests",
        sa.Column("request_body", postgresql.JSONB(none_as_null=True), nullable=True),
        schema="commerce_orders",
    )


def downgrade() -> None:
    op.drop_column("order_action_requests", "request_body", schema="commerce_orders")
