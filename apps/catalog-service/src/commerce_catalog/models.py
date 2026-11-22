"""Catalog-owned persistence models. No cross-service FKs; external IDs stored as values."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from commerce_catalog.db import SPEC, Base


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UpdatedAtMixin:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Category(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("length(name) >= 1", name="name_nonempty"),
        CheckConstraint("length(slug) >= 1", name="slug_nonempty"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_visible: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    products: Mapped[list["Product"]] = relationship("Product", back_populates="category")


class Product(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price_amount >= 0", name="price_nonnegative"),
        CheckConstraint("version >= 0", name="version_nonnegative"),
        CheckConstraint("currency = 'VND'", name="currency_vnd"),
        CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'DISCONTINUED')", name="status_valid"),
        Index("ix_products_category_id_status", "category_id", "status"),
        Index("ix_products_status_price_amount", "status", "price_amount"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    category_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SPEC.schema}.categories.id", ondelete="RESTRICT"),
    )
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    slug: Mapped[str] = mapped_column(String(180), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, server_default=text("''"))
    specifications: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    price_amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'VND'"))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'DRAFT'"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    category: Mapped["Category"] = relationship("Category", back_populates="products")
    images: Mapped[list["ProductImage"]] = relationship(
        "ProductImage", back_populates="product", order_by="ProductImage.sort_order"
    )


class ProductImage(CreatedAtMixin, Base):
    __tablename__ = "product_images"
    __table_args__ = (
        UniqueConstraint("product_id", "sort_order"),
        CheckConstraint("size_bytes > 0", name="size_bytes_positive"),
        CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SPEC.schema}.products.id", ondelete="CASCADE"),
    )
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    mime_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    alt_text: Mapped[str | None] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    product: Mapped["Product"] = relationship("Product", back_populates="images")
