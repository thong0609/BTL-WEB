"""Persist initialization idempotency without changing an already-shared revision."""

from alembic import op

revision = "0003_inventory_initialize"
down_revision = "dc7ce8745220"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_inventory_operations_operation_type_valid"),
        "inventory_operations",
        schema="commerce_inventory",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_inventory_operations_operation_type_valid"),
        "inventory_operations",
        "operation_type IN ('RESERVE', 'RELEASE', 'COMMIT', 'ADJUST', 'INITIALIZE')",
        schema="commerce_inventory",
    )


def downgrade() -> None:
    # Intentionally fails if INITIALIZE history exists; never delete audit data.
    op.drop_constraint(
        op.f("ck_inventory_operations_operation_type_valid"),
        "inventory_operations",
        schema="commerce_inventory",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_inventory_operations_operation_type_valid"),
        "inventory_operations",
        "operation_type IN ('RESERVE', 'RELEASE', 'COMMIT', 'ADJUST')",
        schema="commerce_inventory",
    )
