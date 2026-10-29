"""Foundation revision; schema and roles are created by explicit bootstrap.

Revision ID: 0001_base
Business tables are intentionally not created in setup step 3.
"""

revision = "0001_base"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    # Deliberately never drop the shared-dev schema or roles.
    pass
