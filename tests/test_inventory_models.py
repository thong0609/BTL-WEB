"""Model checks use no dev credentials; DB checks require disposable PostgreSQL."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable

from commerce_inventory.db import SPEC, Base
from commerce_inventory.models import Reservation, StockItem


def test_inventory_mapping_compiles_for_postgresql():
    configure_mappers()
    tables = Base.metadata.sorted_tables
    assert {table.name for table in tables} == {
        "stock_items",
        "reservations",
        "reservation_items",
        "inventory_operations",
        "stock_movements",
        "processed_messages",
        "outbox_messages",
    }
    dialect = postgresql.dialect()
    for table in tables:
        assert table.schema == SPEC.schema
        assert str(CreateTable(table).compile(dialect=dialect))
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table.schema == SPEC.schema
        for index in table.indexes:
            assert str(CreateIndex(index).compile(dialect=dialect))
    assert "available_quantity" not in StockItem.__table__.columns
    query = select(StockItem.product_id).where(StockItem.available_quantity > 0)
    assert "on_hand_quantity - commerce_inventory.stock_items.reserved_quantity" in str(
        query.compile(dialect=dialect)
    )


@pytest.mark.integration
def test_inventory_constraints_on_postgres(postgres_test):
    async def exercise():
        engine = create_async_engine(postgres_test["admin_url"])
        try:
            async with engine.connect() as connection:
                # DDL and sample records are rolled back, even on test failure.
                transaction = await connection.begin()
                try:
                    await connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SPEC.schema}"))
                    await connection.run_sync(Base.metadata.create_all)
                    for on_hand, reserved, threshold in [
                        (-1, 0, 5),
                        (1, -1, 5),
                        (1, 2, 5),
                        (1, 0, -1),
                    ]:
                        with pytest.raises(IntegrityError):
                            async with connection.begin_nested():
                                await connection.execute(
                                    StockItem.__table__.insert().values(
                                        product_id=uuid4(),
                                        on_hand_quantity=on_hand,
                                        reserved_quantity=reserved,
                                        low_stock_threshold=threshold,
                                    )
                                )
                    product_id = uuid4()
                    await connection.execute(
                        StockItem.__table__.insert().values(
                            product_id=product_id,
                            on_hand_quantity=10,
                            reserved_quantity=3,
                        )
                    )
                    available = await connection.scalar(
                        select(StockItem.available_quantity).where(
                            StockItem.product_id == product_id
                        )
                    )
                    assert available == 7
                    order_id = uuid4()
                    await connection.execute(
                        Reservation.__table__.insert().values(
                            order_id=order_id,
                            status="RESERVED",
                        )
                    )
                    with pytest.raises(IntegrityError):
                        async with connection.begin_nested():
                            await connection.execute(
                                Reservation.__table__.insert().values(
                                    order_id=order_id,
                                    status="RESERVED",
                                )
                            )
                    with pytest.raises(IntegrityError):
                        async with connection.begin_nested():
                            await connection.execute(
                                Reservation.__table__.insert().values(
                                    order_id=uuid4(),
                                    status="COMMITTED",
                                    committed_at=text("now()"),
                                    released_at=text("now()"),
                                )
                            )
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(exercise())
