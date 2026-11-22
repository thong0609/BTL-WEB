"""Create catalog business tables: categories, products, product_images.

Revision ID: 0002_catalog_tables
Revises: 0001_base
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_catalog_tables"
down_revision = "0001_base"
branch_labels = None
depends_on = None

SCHEMA = "commerce_catalog"


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_visible", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(name) >= 1", name=op.f("ck_categories_name_nonempty")),
        sa.CheckConstraint("length(slug) >= 1", name=op.f("ck_categories_slug_nonempty")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("slug", name=op.f("uq_categories_slug")),
        schema=SCHEMA,
    )

    op.create_table(
        "products",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=180), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "specifications",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("price_amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'VND'"), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default=sa.text("'DRAFT'"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("currency = 'VND'", name=op.f("ck_products_currency_vnd")),
        sa.CheckConstraint("price_amount >= 0", name=op.f("ck_products_price_nonnegative")),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'DISCONTINUED')",
            name=op.f("ck_products_status_valid"),
        ),
        sa.CheckConstraint("version >= 0", name=op.f("ck_products_version_nonnegative")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            [f"{SCHEMA}.categories.id"],
            name=op.f("fk_products_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("sku", name=op.f("uq_products_sku")),
        sa.UniqueConstraint("slug", name=op.f("uq_products_slug")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_products_category_id_status",
        "products",
        ["category_id", "status"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_products_status_price_amount",
        "products",
        ["status", "price_amount"],
        unique=False,
        schema=SCHEMA,
    )

    op.create_table(
        "product_images",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=50), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("alt_text", sa.String(length=255), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_product_images_size_bytes_positive")),
        sa.CheckConstraint(
            "sort_order >= 0", name=op.f("ck_product_images_sort_order_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            [f"{SCHEMA}.products.id"],
            name=op.f("fk_product_images_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_images")),
        sa.UniqueConstraint("product_id", "sort_order", name=op.f("uq_product_images_product_id")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_product_images_storage_key")),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("product_images", schema=SCHEMA)
    op.drop_index("ix_products_status_price_amount", table_name="products", schema=SCHEMA)
    op.drop_index("ix_products_category_id_status", table_name="products", schema=SCHEMA)
    op.drop_table("products", schema=SCHEMA)
    op.drop_table("categories", schema=SCHEMA)
