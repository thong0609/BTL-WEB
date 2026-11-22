"""Catalog model compilation, schema validation, and PostgreSQL constraint tests."""

import asyncio
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable

from commerce_catalog.db import SPEC, Base
from commerce_catalog.models import Category, Product, ProductImage
from commerce_catalog.schemas import (
    CategoryInput,
    CategoryPatch,
    InternalBatchRequest,
    ProductInput,
    ProductOut,
    ProductPatch,
)


def test_catalog_mapping_compiles_for_postgresql() -> None:
    configure_mappers()
    tables = Base.metadata.sorted_tables
    assert {table.name for table in tables} == {
        "categories",
        "products",
        "product_images",
    }
    dialect = postgresql.dialect()
    for table in tables:
        assert table.schema == SPEC.schema
        assert str(CreateTable(table).compile(dialect=dialect))
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table.schema == SPEC.schema
        for index in table.indexes:
            assert str(CreateIndex(index).compile(dialect=dialect))


def test_category_input_and_patch_validation() -> None:
    inp = CategoryInput(
        name="  Phím Cơ  ",
        slug="phim-co",
        description="Bàn phím cơ",
        is_visible=True,
    )
    assert inp.name == "Phím Cơ"
    assert inp.slug == "phim-co"
    assert inp.is_visible is True

    with pytest.raises(ValidationError):
        CategoryInput(name="   ", slug="phim-co")

    for bad_slug in ("Chuột", "chuot_quang", "chuot quang", "-chuot", "chuot-", "a--b"):
        with pytest.raises(ValidationError):
            CategoryInput(name="Chuột", slug=bad_slug)

    with pytest.raises(ValidationError):
        CategoryPatch()

    with pytest.raises(ValidationError):
        CategoryPatch.model_validate({"name": None})

    patch = CategoryPatch(name="Bàn phím mới", description=None)
    assert patch.name == "Bàn phím mới"
    assert "description" in patch.model_fields_set


def test_product_input_and_patch_validation() -> None:
    cat_id = uuid4()
    inp_str = ProductInput.model_validate(
        {
            "sku": " KB-01 ",
            "slug": "ban-phim-co-01",
            "name": " Bàn phím cơ ",
            "categoryId": str(cat_id),
            "description": "Mô tả",
            "priceAmount": "450000",
            "currency": "VND",
            "status": "ACTIVE",
            "specifications": {"switch": "Blue"},
        }
    )
    assert inp_str.sku == "KB-01"
    assert inp_str.name == "Bàn phím cơ"
    assert inp_str.price_amount == 450000

    inp_int = ProductInput(
        sku="KB-02",
        slug="ban-phim-co-02",
        name="Bàn phím",
        category_id=cat_id,
        price_amount=0,
    )
    assert inp_int.price_amount == 0
    assert inp_int.status == "DRAFT"

    for bad_price in (-1, "-500", 12.5, True, "abc", ""):
        with pytest.raises(ValidationError):
            ProductInput.model_validate(
                {
                    "sku": "KB-BAD",
                    "slug": "kb-bad",
                    "name": "Bad",
                    "categoryId": str(cat_id),
                    "priceAmount": bad_price,
                }
            )

    with pytest.raises(ValidationError):
        ProductInput(
            sku="   ",
            slug="ban-phim-co-03",
            name="Bàn phím",
            category_id=cat_id,
            price_amount=100000,
        )

    with pytest.raises(ValidationError):
        ProductPatch(expected_version=0)

    dup_id = uuid4()
    with pytest.raises(ValidationError):
        ProductPatch(expected_version=1, image_ids=[dup_id, dup_id])

    with pytest.raises(ValidationError):
        ProductPatch(expected_version=1, image_ids=[uuid4() for _ in range(6)])

    patch = ProductPatch.model_validate({"expectedVersion": 2, "priceAmount": "500000"})
    assert patch.expected_version == 2
    assert patch.price_amount == 500000


def test_internal_batch_request_validation() -> None:
    uid = uuid4()
    req = InternalBatchRequest.model_validate({"productIds": [str(uid)]})
    assert req.product_ids == [uid]

    with pytest.raises(ValidationError):
        InternalBatchRequest.model_validate({"productIds": []})

    with pytest.raises(ValidationError):
        InternalBatchRequest.model_validate({"productIds": [str(uid), str(uid)]})

    with pytest.raises(ValidationError):
        InternalBatchRequest.model_validate({"productIds": [str(uuid4()) for _ in range(51)]})


def test_product_out_wire_serialization() -> None:
    pid = uuid4()
    cid = uuid4()
    p = ProductOut(
        id=pid,
        sku="TEST-SKU",
        slug="test-product",
        name="Test Product",
        category_id=cid,
        description="Mô tả",
        specifications={"color": "black"},
        price_amount=430000,
        currency="VND",
        status="ACTIVE",
        version=0,
        images=[],
        availability="IN_STOCK",
    )
    dump = p.model_dump(mode="json", by_alias=True)
    assert dump["id"] == str(pid)
    assert dump["categoryId"] == str(cid)
    assert dump["priceAmount"] == "430000"
    assert dump["availability"] == "IN_STOCK"
    assert dump["images"] == []


@pytest.mark.integration
def test_catalog_constraints_on_postgres(postgres_test) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_test["admin_url"])
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    await connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SPEC.schema}"))
                    await connection.run_sync(Base.metadata.create_all)

                    cat_id = uuid4()
                    await connection.execute(
                        Category.__table__.insert().values(
                            id=cat_id,
                            name="Bàn phím",
                            slug="ban-phim",
                            is_visible=True,
                        )
                    )
                    # Duplicate category slug rejected
                    with pytest.raises(IntegrityError):
                        async with connection.begin_nested():
                            await connection.execute(
                                Category.__table__.insert().values(
                                    id=uuid4(),
                                    name="Khác",
                                    slug="ban-phim",
                                )
                            )

                    prod_id = uuid4()
                    await connection.execute(
                        Product.__table__.insert().values(
                            id=prod_id,
                            category_id=cat_id,
                            sku="SKU-1",
                            slug="prod-1",
                            name="Sản phẩm 1",
                            description="Mô tả",
                            price_amount=100000,
                            currency="VND",
                            status="ACTIVE",
                        )
                    )

                    # Invalid price_amount, currency, status, version rejected
                    for bad_values in (
                        {"price_amount": -1},
                        {"currency": "USD"},
                        {"status": "ARCHIVED"},
                        {"version": -1},
                        {"sku": "SKU-1"},
                        {"slug": "prod-1"},
                    ):
                        row = {
                            "id": uuid4(),
                            "category_id": cat_id,
                            "sku": f"SKU-{uuid4().hex[:6]}",
                            "slug": f"slug-{uuid4().hex[:6]}",
                            "name": "SP",
                            "description": "",
                            "price_amount": 1000,
                            "currency": "VND",
                            "status": "DRAFT",
                            "version": 0,
                            **bad_values,
                        }
                        with pytest.raises(IntegrityError):
                            async with connection.begin_nested():
                                await connection.execute(Product.__table__.insert().values(**row))

                    # RESTRICT prevents deleting category referenced by product
                    with pytest.raises(IntegrityError):
                        async with connection.begin_nested():
                            await connection.execute(
                                Category.__table__.delete().where(Category.id == cat_id)
                            )

                    # Image constraints: size_bytes > 0, sort_order >= 0, unique sort_order
                    await connection.execute(
                        ProductImage.__table__.insert().values(
                            id=uuid4(),
                            product_id=prod_id,
                            storage_key=f"{prod_id}/img0.png",
                            mime_type="image/png",
                            size_bytes=128,
                            sort_order=0,
                        )
                    )
                    with pytest.raises(IntegrityError):
                        async with connection.begin_nested():
                            await connection.execute(
                                ProductImage.__table__.insert().values(
                                    id=uuid4(),
                                    product_id=prod_id,
                                    storage_key=f"{prod_id}/img1.png",
                                    mime_type="image/png",
                                    size_bytes=128,
                                    sort_order=0,
                                )
                            )
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(exercise())
