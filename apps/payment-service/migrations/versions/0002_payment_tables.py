"""Payment tables and the singleton demo configuration.

Revision ID: 0002_payment_tables
Revises: 0001_base
"""

import sqlalchemy as sa
from alembic import op

from commerce_payment.models import Base

revision = "0002_payment_tables"
down_revision = "0001_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind(), checkfirst=False)
    op.execute(
        sa.text(
            "INSERT INTO commerce_payments.demo_configuration "
            "(id, payment_scenario, refund_scenario, delay_seconds, version, "
            "updated_by, updated_at) "
            "VALUES (1, 'SUCCESS', 'SUCCESS', 0, 1, NULL, CURRENT_TIMESTAMP)"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO commerce_payments.demo_configuration_history "
            "(id, configuration_id, version, snapshot, actor_id, created_at) "
            "VALUES ("
            "'00000000-0000-4000-8000-000000000001', 1, 1, "
            "CAST(:snapshot AS jsonb), NULL, CURRENT_TIMESTAMP)"
        ).bindparams(
            snapshot=('{"paymentScenario":"SUCCESS","refundScenario":"SUCCESS","delaySeconds":0}')
        )
    )


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
