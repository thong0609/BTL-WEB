"""Create the eight Order-owned tables and protect append-only status history.

Revision ID: 0002_order_tables
Revises: 0001_base
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_order_tables"
down_revision = "0001_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("order_number", sa.String(length=32), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PROCESSING",
                "AWAITING_CONFIRMATION",
                "PREPARING",
                "SHIPPING",
                "COMPLETED",
                "CANCELLING",
                "CANCELLED",
                "REJECTED",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=30,
                schema="commerce_orders",
            ),
            nullable=False,
        ),
        sa.Column(
            "payment_method",
            sa.Enum(
                "COD",
                "SIMULATED",
                name="payment_method",
                native_enum=False,
                create_constraint=True,
                length=20,
                schema="commerce_orders",
            ),
            nullable=False,
        ),
        sa.Column("payment_id", sa.Uuid(), nullable=True),
        sa.Column(
            "payment_status",
            sa.Enum(
                "PENDING",
                "AWAITING_COLLECTION",
                "SUCCEEDED",
                "FAILED",
                "REFUND_PENDING",
                "REFUNDED",
                "CANCELLED",
                name="payment_status",
                native_enum=False,
                create_constraint=True,
                length=30,
                schema="commerce_orders",
            ),
            nullable=True,
        ),
        sa.Column("payment_version", sa.Integer(), nullable=True),
        sa.Column("recipient_name", sa.String(length=150), nullable=False),
        sa.Column("recipient_phone", sa.String(length=30), nullable=False),
        sa.Column("shipping_address", sa.Text(), nullable=False),
        sa.Column("customer_note", sa.Text(), nullable=True),
        sa.Column("subtotal_amount", sa.BigInteger(), nullable=False),
        sa.Column("shipping_fee_amount", sa.BigInteger(), nullable=False),
        sa.Column("total_amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'VND'"), nullable=False),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("rejection_code", sa.String(length=64), nullable=True),
        sa.Column(
            "requires_attention", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("exception_note", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("currency = 'VND'", name=op.f("ck_orders_currency_vnd")),
        sa.CheckConstraint(
            "payment_version >= 0", name=op.f("ck_orders_payment_version_nonnegative")
        ),
        sa.CheckConstraint(
            "shipping_fee_amount >= 0", name=op.f("ck_orders_shipping_fee_nonnegative")
        ),
        sa.CheckConstraint("subtotal_amount >= 0", name=op.f("ck_orders_subtotal_nonnegative")),
        sa.CheckConstraint(
            "total_amount = subtotal_amount + shipping_fee_amount", name=op.f("ck_orders_total_sum")
        ),
        sa.CheckConstraint("total_amount >= 0", name=op.f("ck_orders_total_nonnegative")),
        sa.CheckConstraint("version >= 0", name=op.f("ck_orders_version_nonnegative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("order_number", name=op.f("uq_orders_order_number")),
        schema="commerce_orders",
    )
    op.create_index(
        "ix_orders_created_id",
        "orders",
        ["created_at", "id"],
        unique=False,
        schema="commerce_orders",
    )
    op.create_index(
        "ix_orders_customer_created_id",
        "orders",
        ["customer_id", "created_at", "id"],
        unique=False,
        schema="commerce_orders",
    )
    op.create_index(
        "ix_orders_status_created_id",
        "orders",
        ["status", "created_at", "id"],
        unique=False,
        schema="commerce_orders",
    )
    op.create_table(
        "outbox_messages",
        sa.Column("message_type", sa.String(length=100), nullable=False),
        sa.Column("message_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("aggregate_type", sa.String(length=50), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=True),
        sa.Column("exchange_name", sa.String(length=100), nullable=False),
        sa.Column("routing_key", sa.String(length=150), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("causation_id", sa.Uuid(), nullable=True),
        sa.Column(
            "payload", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "PROCESSING",
                "PUBLISHED",
                "NEEDS_ATTENTION",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=20,
                schema="commerce_orders",
            ),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("locked_by", sa.String(length=100), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "aggregate_type IN ('ORDER', 'RESERVATION', 'PAYMENT', 'REFUND')",
            name=op.f("ck_outbox_messages_aggregate_type"),
        ),
        sa.CheckConstraint(
            "exchange_name IN ('commerce.commands', 'commerce.events')",
            name=op.f("ck_outbox_messages_exchange_name"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name=op.f("ck_outbox_messages_payload_object")
        ),
        sa.CheckConstraint(
            "aggregate_version >= 0", name=op.f("ck_outbox_messages_aggregate_version_nonnegative")
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name=op.f("ck_outbox_messages_attempt_count_nonnegative")
        ),
        sa.CheckConstraint(
            "message_version >= 1", name=op.f("ck_outbox_messages_message_version_positive")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_messages")),
        schema="commerce_orders",
    )
    op.create_index(
        "ix_outbox_messages_aggregate",
        "outbox_messages",
        ["aggregate_type", "aggregate_id"],
        unique=False,
        schema="commerce_orders",
    )
    op.create_index(
        "ix_outbox_messages_locked_until",
        "outbox_messages",
        ["locked_until"],
        unique=False,
        schema="commerce_orders",
    )
    op.create_index(
        "ix_outbox_messages_status_next_attempt_id",
        "outbox_messages",
        ["status", "next_attempt_at", "id"],
        unique=False,
        schema="commerce_orders",
    )
    op.create_table(
        "processed_messages",
        sa.Column("consumer_name", sa.String(length=100), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("message_type", sa.String(length=100), nullable=False),
        sa.Column("message_version", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_processed_messages_payload_hash_sha256"),
        ),
        sa.CheckConstraint(
            "length(consumer_name) > 0", name=op.f("ck_processed_messages_consumer_nonempty")
        ),
        sa.CheckConstraint(
            "message_version >= 1", name=op.f("ck_processed_messages_message_version_positive")
        ),
        sa.PrimaryKeyConstraint("consumer_name", "message_id", name=op.f("pk_processed_messages")),
        schema="commerce_orders",
    )
    op.create_table(
        "idempotency_requests",
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column(
            "response_body",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(response_body) = 'object'",
            name=op.f("ck_idempotency_requests_response_body_object"),
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_idempotency_requests_request_hash_sha256"),
        ),
        sa.CheckConstraint(
            "length(idempotency_key) > 0", name=op.f("ck_idempotency_requests_key_nonempty")
        ),
        sa.CheckConstraint(
            "length(scope) > 0", name=op.f("ck_idempotency_requests_scope_nonempty")
        ),
        sa.CheckConstraint(
            "response_status BETWEEN 100 AND 599",
            name=op.f("ck_idempotency_requests_http_status_range"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["commerce_orders.orders.id"],
            name=op.f("fk_idempotency_requests_order_id_orders"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_requests")),
        sa.UniqueConstraint(
            "customer_id",
            "scope",
            "idempotency_key",
            name=op.f("uq_idempotency_requests_customer_id"),
        ),
        schema="commerce_orders",
    )
    op.create_table(
        "order_action_requests",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column(
            "action",
            sa.Enum(
                "CANCEL",
                "CONFIRM",
                "DISPATCH",
                "COMPLETE",
                "RECORD_EXCEPTION",
                name="action",
                native_enum=False,
                create_constraint=True,
                length=30,
                schema="commerce_orders",
            ),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column(
            "response_body",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(response_body) = 'object'",
            name=op.f("ck_order_action_requests_response_body_object"),
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_order_action_requests_request_hash_sha256"),
        ),
        sa.CheckConstraint(
            "length(idempotency_key) > 0", name=op.f("ck_order_action_requests_key_nonempty")
        ),
        sa.CheckConstraint(
            "response_status BETWEEN 100 AND 599",
            name=op.f("ck_order_action_requests_http_status_range"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["commerce_orders.orders.id"],
            name=op.f("fk_order_action_requests_order_id_orders"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_action_requests")),
        sa.UniqueConstraint(
            "actor_id",
            "order_id",
            "action",
            "idempotency_key",
            name=op.f("uq_order_action_requests_actor_id"),
        ),
        schema="commerce_orders",
    )
    op.create_table(
        "order_items",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("product_sku", sa.String(length=64), nullable=False),
        sa.Column("product_name", sa.String(length=200), nullable=False),
        sa.Column("catalog_version", sa.Integer(), nullable=False),
        sa.Column("unit_price_amount", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("line_total_amount", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "catalog_version >= 0", name=op.f("ck_order_items_catalog_version_nonnegative")
        ),
        sa.CheckConstraint(
            "line_total_amount = unit_price_amount * quantity",
            name=op.f("ck_order_items_line_total_product"),
        ),
        sa.CheckConstraint(
            "line_total_amount >= 0", name=op.f("ck_order_items_line_total_nonnegative")
        ),
        sa.CheckConstraint(
            "quantity BETWEEN 1 AND 999", name=op.f("ck_order_items_quantity_range")
        ),
        sa.CheckConstraint(
            "unit_price_amount >= 0", name=op.f("ck_order_items_unit_price_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["commerce_orders.orders.id"], name=op.f("fk_order_items_order_id_orders")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_items")),
        sa.UniqueConstraint("order_id", "product_id", name="uq_order_items_order_product"),
        sa.UniqueConstraint("order_id", "product_sku", name="uq_order_items_order_sku"),
        schema="commerce_orders",
    )
    op.create_table(
        "order_status_history",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column(
            "from_status",
            sa.Enum(
                "PROCESSING",
                "AWAITING_CONFIRMATION",
                "PREPARING",
                "SHIPPING",
                "COMPLETED",
                "CANCELLING",
                "CANCELLED",
                "REJECTED",
                name="from_status",
                native_enum=False,
                create_constraint=True,
                length=30,
                schema="commerce_orders",
            ),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            sa.Enum(
                "PROCESSING",
                "AWAITING_CONFIRMATION",
                "PREPARING",
                "SHIPPING",
                "COMPLETED",
                "CANCELLING",
                "CANCELLED",
                "REJECTED",
                name="to_status",
                native_enum=False,
                create_constraint=True,
                length=30,
                schema="commerce_orders",
            ),
            nullable=False,
        ),
        sa.Column(
            "actor_type",
            sa.Enum(
                "CUSTOMER",
                "ADMIN",
                "SYSTEM",
                name="actor_type",
                native_enum=False,
                create_constraint=True,
                length=20,
                schema="commerce_orders",
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["commerce_orders.orders.id"],
            name=op.f("fk_order_status_history_order_id_orders"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_status_history")),
        schema="commerce_orders",
    )
    op.create_index(
        "ix_order_status_history_order_created_id",
        "order_status_history",
        ["order_id", "created_at", "id"],
        unique=False,
        schema="commerce_orders",
    )
    op.create_table(
        "order_workflows",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column(
            "phase",
            sa.Enum(
                "CHECKOUT",
                "IDLE",
                "CANCELLATION",
                "DISPATCH",
                "COMPLETION",
                name="phase",
                native_enum=False,
                create_constraint=True,
                length=30,
                schema="commerce_orders",
            ),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.Enum(
                "RUNNING",
                "WAITING",
                "DONE",
                "NEEDS_ATTENTION",
                name="state",
                native_enum=False,
                create_constraint=True,
                length=20,
                schema="commerce_orders",
            ),
            nullable=False,
        ),
        sa.Column(
            "stock_step",
            sa.Enum(
                "NOT_REQUESTED",
                "RESERVE_PENDING",
                "RESERVED",
                "RESERVE_FAILED",
                "RELEASE_PENDING",
                "RELEASED",
                "COMMIT_PENDING",
                "COMMITTED",
                name="stock_step",
                native_enum=False,
                create_constraint=True,
                length=30,
                schema="commerce_orders",
            ),
            nullable=False,
        ),
        sa.Column(
            "payment_step",
            sa.Enum(
                "NOT_REQUESTED",
                "INIT_PENDING",
                "PENDING",
                "COD_READY",
                "PAID",
                "FAILED",
                "CANCEL_PENDING",
                "CANCELLED",
                "REFUND_PENDING",
                "REFUNDED",
                "COLLECT_PENDING",
                name="payment_step",
                native_enum=False,
                create_constraint=True,
                length=30,
                schema="commerce_orders",
            ),
            nullable=False,
        ),
        sa.Column("reservation_id", sa.Uuid(), nullable=True),
        sa.Column("reserve_operation_id", sa.Uuid(), nullable=True),
        sa.Column("release_operation_id", sa.Uuid(), nullable=True),
        sa.Column("commit_operation_id", sa.Uuid(), nullable=True),
        sa.Column("payment_operation_id", sa.Uuid(), nullable=True),
        sa.Column("refund_operation_id", sa.Uuid(), nullable=True),
        sa.Column("cancel_payment_operation_id", sa.Uuid(), nullable=True),
        sa.Column("collection_operation_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "retry_count >= 0", name=op.f("ck_order_workflows_retry_count_nonnegative")
        ),
        sa.CheckConstraint("version >= 0", name=op.f("ck_order_workflows_version_nonnegative")),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["commerce_orders.orders.id"],
            name=op.f("fk_order_workflows_order_id_orders"),
        ),
        sa.PrimaryKeyConstraint("order_id", name=op.f("pk_order_workflows")),
        schema="commerce_orders",
    )
    op.create_index(
        "ix_order_workflows_state_next_retry",
        "order_workflows",
        ["state", "next_retry_at"],
        unique=False,
        schema="commerce_orders",
    )
    op.execute("""
        CREATE FUNCTION commerce_orders.reject_status_history_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $function$
        BEGIN
            RAISE EXCEPTION USING
                ERRCODE = '23514', MESSAGE = 'Order status history is append-only';
        END;
        $function$
    """)
    op.execute("""
        CREATE TRIGGER order_status_history_append_only
        BEFORE UPDATE OR DELETE ON commerce_orders.order_status_history
        FOR EACH ROW EXECUTE FUNCTION commerce_orders.reject_status_history_mutation()
    """)


def downgrade() -> None:
    op.drop_index(
        "ix_order_workflows_state_next_retry",
        table_name="order_workflows",
        schema="commerce_orders",
    )
    op.drop_table("order_workflows", schema="commerce_orders")
    op.drop_index(
        "ix_order_status_history_order_created_id",
        table_name="order_status_history",
        schema="commerce_orders",
    )
    op.drop_table("order_status_history", schema="commerce_orders")
    op.drop_table("order_items", schema="commerce_orders")
    op.drop_table("order_action_requests", schema="commerce_orders")
    op.drop_table("idempotency_requests", schema="commerce_orders")
    op.drop_table("processed_messages", schema="commerce_orders")
    op.drop_index(
        "ix_outbox_messages_status_next_attempt_id",
        table_name="outbox_messages",
        schema="commerce_orders",
    )
    op.drop_index(
        "ix_outbox_messages_locked_until", table_name="outbox_messages", schema="commerce_orders"
    )
    op.drop_index(
        "ix_outbox_messages_aggregate", table_name="outbox_messages", schema="commerce_orders"
    )
    op.drop_table("outbox_messages", schema="commerce_orders")
    op.drop_index("ix_orders_status_created_id", table_name="orders", schema="commerce_orders")
    op.drop_index("ix_orders_customer_created_id", table_name="orders", schema="commerce_orders")
    op.drop_index("ix_orders_created_id", table_name="orders", schema="commerce_orders")
    op.drop_table("orders", schema="commerce_orders")
    op.execute("DROP FUNCTION commerce_orders.reject_status_history_mutation()")
