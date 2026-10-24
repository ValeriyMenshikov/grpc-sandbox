"""SQL репозитория против Postgres из compose (make up) во временной базе.

Без доступного Postgres тесты пропускаются: unit-тесты хэндлеров обходятся без него.
Адрес — env TEST_POSTGRES_DSN, по умолчанию Postgres из compose на localhost.
"""

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import timedelta

import asyncpg
import pytest
from catalog_service.models import ImportItem, ImportMode, ImportOutcome, ProductFilter, ProductSort
from catalog_service.repository import CatalogRepository
from stand_core.clients import Postgres
from stand_core.settings import Settings

ADMIN_DSN = os.environ.get("TEST_POSTGRES_DSN", "postgresql://stand:stand@localhost:5432/stand")
SEED_SELLER_ID = "00000000-0000-4000-8000-000000000001"
SELLER = "seller-under-test"


@pytest.fixture
async def postgres(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Postgres]:
    try:
        admin = await asyncpg.connect(ADMIN_DSN, timeout=2)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres is not available ({exc}); run make up")
    database = f"catalog_test_{uuid.uuid4().hex[:12]}"
    await admin.execute(f'CREATE DATABASE "{database}"')
    monkeypatch.setenv("POSTGRES_DSN", f"{ADMIN_DSN.rsplit('/', 1)[0]}/{database}")
    client = Postgres(Settings())
    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.close()


@pytest.fixture
async def repository(postgres: Postgres) -> CatalogRepository:
    repository = CatalogRepository(postgres)
    await repository.connect()
    return repository


def item(offer_id: str, name: str = "Товар", price: int = 1000, stock: int = 3) -> ImportItem:
    return ImportItem(
        offer_id=offer_id, name=name, category="test", price_kopecks=price, stock=stock
    )


async def test_schema_is_idempotent_and_seeds_products(
    repository: CatalogRepository, postgres: Postgres
) -> None:
    await repository.connect()

    seeds = await postgres.pool.fetch(
        "SELECT category, count(*) FROM catalog.products WHERE seller_id = $1 GROUP BY category",
        SEED_SELLER_ID,
    )
    assert 20 <= sum(row["count"] for row in seeds) <= 30
    assert 3 <= len(seeds) <= 4
    in_stock = await postgres.pool.fetchval(
        "SELECT count(*) FROM catalog.stocks WHERE quantity > 0"
    )
    assert in_stock >= 20


async def test_import_upsert_and_create_only(repository: CatalogRepository) -> None:
    first = await repository.import_products(
        SELLER, ImportMode.UPSERT, [item("A", "Альфа"), item("B")]
    )
    second = await repository.import_products(
        SELLER, ImportMode.UPSERT, [item("A", "Альфа 2", price=2000, stock=9)]
    )
    third = await repository.import_products(SELLER, ImportMode.CREATE_ONLY, [item("B"), item("C")])

    assert first == [ImportOutcome.CREATED, ImportOutcome.CREATED]
    assert second == [ImportOutcome.UPDATED]
    assert third == [ImportOutcome.ALREADY_EXISTS, ImportOutcome.CREATED]
    found = await repository.search_products(ProductFilter(query="альфа"), 0, 10)
    assert [(p.name, p.price_kopecks, p.stock) for p in found] == [("Альфа 2", 2000, 9)]
    assert found[0].updated_at > found[0].created_at


async def test_search_filters_sort_and_offset(repository: CatalogRepository) -> None:
    await repository.import_products(
        SELLER,
        ImportMode.UPSERT,
        [item("A", "Тест А", price=300), item("B", "Тест Б", price=100), item("C", "Тест В", 200)],
    )
    tests = ProductFilter(query="тест", category="test", sort=ProductSort.PRICE_ASC)

    page = await repository.search_products(tests, 1, 5)
    ranged = await repository.search_products(
        ProductFilter(category="test", min_price_kopecks=150, max_price_kopecks=250), 0, 5
    )
    by_name = await repository.search_products(ProductFilter(category="test"), 0, 5)

    assert [p.price_kopecks for p in page] == [200, 300]
    assert [p.offer_id for p in ranged] == ["C"]
    assert [p.name for p in by_name] == ["Тест А", "Тест Б", "Тест В"]


async def test_stock_excludes_reservations(
    repository: CatalogRepository, postgres: Postgres
) -> None:
    await repository.import_products(SELLER, ImportMode.UPSERT, [item("A", stock=5)])
    [product] = await repository.search_products(ProductFilter(category="test"), 0, 5)
    await postgres.pool.execute(
        "INSERT INTO catalog.reservations (order_id, product_id, quantity) VALUES ('o1', $1, 2)",
        product.product_id,
    )

    reloaded = await repository.get_product(product.product_id)

    assert reloaded is not None
    assert reloaded.stock == 3
    assert type(reloaded.stock) is int
    assert await repository.get_product("missing") is None


async def test_export_streams_seller_products_since(repository: CatalogRepository) -> None:
    await repository.import_products(SELLER, ImportMode.UPSERT, [item("A"), item("B")])
    await repository.import_products("other-seller", ImportMode.UPSERT, [item("X")])
    [later] = await repository.import_products(SELLER, ImportMode.UPSERT, [item("C")])
    assert later is ImportOutcome.CREATED

    async with aclosing(repository.export_products(SELLER, None)) as products:
        everything = [p.offer_id async for p in products]
    newest = await repository.search_products(ProductFilter(sort=ProductSort.NEWEST), 0, 1)
    since = newest[0].updated_at - timedelta(microseconds=1)
    async with aclosing(repository.export_products(SELLER, since)) as products:
        recent = [p.offer_id async for p in products]

    # A и B из одного импорта: одинаковый updated_at, порядок между ними — по product_id
    assert sorted(everything[:2]) == ["A", "B"]
    assert everything[2] == "C"
    assert recent == ["C"]
