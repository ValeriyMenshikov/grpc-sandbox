"""Репозиторий каталога поверх Postgres (схема `catalog`, см. schema.sql)."""

from collections.abc import AsyncGenerator, Sequence
from datetime import datetime
from pathlib import Path

import asyncpg
from nuke_di import Client
from stand_core.clients import Postgres

from catalog_service.models import (
    ImportItem,
    ImportMode,
    ImportOutcome,
    Product,
    ProductFilter,
    ProductSort,
    ReserveResult,
    StockItem,
    StockShortage,
)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Товар с доступным остатком: остаток на складе минус резервы, не меньше нуля
_PRODUCT_SELECT = """
SELECT p.product_id, p.seller_id, p.offer_id, p.name, p.category, p.price_kopecks,
       p.created_at, p.updated_at,
       GREATEST(COALESCE(s.quantity, 0) - COALESCE(r.reserved, 0), 0) AS stock
FROM catalog.products AS p
LEFT JOIN catalog.stocks AS s ON s.product_id = p.product_id
LEFT JOIN LATERAL (
    -- sum(bigint) в Postgres — numeric (Decimal в asyncpg), а остаток в proto — int64
    SELECT sum(quantity)::bigint AS reserved
    FROM catalog.reservations
    WHERE product_id = p.product_id
) AS r ON true
"""

# product_id в конце — стабильный порядок при равных значениях, иначе страницы «плывут»
_ORDER_BY: dict[ProductSort, str] = {
    ProductSort.NAME: "p.name, p.product_id",
    ProductSort.PRICE_ASC: "p.price_kopecks, p.product_id",
    ProductSort.PRICE_DESC: "p.price_kopecks DESC, p.product_id",
    ProductSort.NEWEST: "p.updated_at DESC, p.product_id",
}

_UPSERT_PRODUCT = """
INSERT INTO catalog.products (seller_id, offer_id, name, category, price_kopecks)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (seller_id, offer_id) DO UPDATE
SET name = EXCLUDED.name,
    category = EXCLUDED.category,
    price_kopecks = EXCLUDED.price_kopecks,
    updated_at = now()
RETURNING product_id, (xmax = 0) AS created
"""

_CREATE_PRODUCT = """
INSERT INTO catalog.products (seller_id, offer_id, name, category, price_kopecks)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (seller_id, offer_id) DO NOTHING
RETURNING product_id, true AS created
"""

_SET_STOCK = """
INSERT INTO catalog.stocks (product_id, quantity) VALUES ($1, $2)
ON CONFLICT (product_id) DO UPDATE SET quantity = EXCLUDED.quantity
"""

_AVAILABLE = """
SELECT GREATEST(COALESCE(s.quantity, 0) - COALESCE(
           (SELECT sum(quantity)::bigint FROM catalog.reservations WHERE product_id = p.product_id),
           0), 0) AS available
FROM catalog.products AS p
LEFT JOIN catalog.stocks AS s ON s.product_id = p.product_id
WHERE p.product_id = $1
"""

# Блокировка строк товаров в порядке product_id: параллельные резервы одних товаров
# выстраиваются в очередь и не ловят deadlock
_LOCK_STOCKS = """
SELECT p.product_id, COALESCE(s.quantity, 0) AS quantity
FROM catalog.products AS p
LEFT JOIN catalog.stocks AS s ON s.product_id = p.product_id
WHERE p.product_id = ANY($1::text[])
ORDER BY p.product_id
FOR UPDATE OF p
"""

_RESERVED = """
SELECT product_id, sum(quantity)::bigint AS reserved
FROM catalog.reservations
WHERE product_id = ANY($1::text[])
GROUP BY product_id
"""

_ORDER_RESERVATIONS = """
SELECT product_id, quantity FROM catalog.reservations WHERE order_id = $1 ORDER BY product_id
"""

EXPORT_PREFETCH = 100


def _product(record: asyncpg.Record) -> Product:
    return Product(
        product_id=record["product_id"],
        seller_id=record["seller_id"],
        offer_id=record["offer_id"],
        name=record["name"],
        category=record["category"],
        price_kopecks=record["price_kopecks"],
        stock=record["stock"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


class CatalogRepository(Client):
    """Товары, остатки и резервы. Схема и сиды применяются в `connect()`."""

    def __init__(self, postgres: Postgres) -> None:
        self._postgres = postgres

    async def connect(self) -> None:
        await self._postgres.apply_schema(SCHEMA_PATH)

    async def get_product(self, product_id: str) -> Product | None:
        record = await self._postgres.pool.fetchrow(
            f"{_PRODUCT_SELECT} WHERE p.product_id = $1", product_id
        )
        return None if record is None else _product(record)

    async def search_products(
        self, product_filter: ProductFilter, offset: int, limit: int
    ) -> list[Product]:
        conditions = [
            "($1 = '' OR strpos(lower(p.name), lower($1)) > 0)",
            "($2::text IS NULL OR p.category = $2)",
            "($3::bigint IS NULL OR p.price_kopecks >= $3)",
            "($4::bigint IS NULL OR p.price_kopecks <= $4)",
        ]
        records = await self._postgres.pool.fetch(
            f"{_PRODUCT_SELECT} WHERE {' AND '.join(conditions)} "
            f"ORDER BY {_ORDER_BY[product_filter.sort]} OFFSET $5 LIMIT $6",
            product_filter.query,
            product_filter.category,
            product_filter.min_price_kopecks,
            product_filter.max_price_kopecks,
            offset,
            limit,
        )
        return [_product(record) for record in records]

    async def import_products(
        self, seller_id: str, mode: ImportMode, items: Sequence[ImportItem]
    ) -> list[ImportOutcome]:
        """Применить строки одной транзакцией; исход — по каждой строке, в том же порядке."""
        query = _UPSERT_PRODUCT if mode is ImportMode.UPSERT else _CREATE_PRODUCT
        outcomes: list[ImportOutcome] = []
        async with self._postgres.pool.acquire() as connection, connection.transaction():
            for item in items:
                record = await connection.fetchrow(
                    query, seller_id, item.offer_id, item.name, item.category, item.price_kopecks
                )
                if record is None:
                    outcomes.append(ImportOutcome.ALREADY_EXISTS)
                    continue
                await connection.execute(_SET_STOCK, record["product_id"], item.stock)
                outcomes.append(
                    ImportOutcome.CREATED if record["created"] else ImportOutcome.UPDATED
                )
        return outcomes

    async def export_products(
        self, seller_id: str, updated_since: datetime | None
    ) -> AsyncGenerator[Product, None]:
        """Товары продавца курсором, без загрузки всего каталога в память.

        Соединение занято, пока генератор не закрыт: вызывающий закрывает его через `aclosing`.
        """
        async with self._postgres.pool.acquire() as connection, connection.transaction():
            cursor = connection.cursor(
                f"{_PRODUCT_SELECT} WHERE p.seller_id = $1 "
                "AND ($2::timestamptz IS NULL OR p.updated_at >= $2) "
                "ORDER BY p.updated_at, p.product_id",
                seller_id,
                updated_since,
                prefetch=EXPORT_PREFETCH,
            )
            async for record in cursor:
                yield _product(record)

    async def get_available(self, product_id: str) -> int | None:
        """Доступный остаток (остаток минус резервы); None — товара нет."""
        record = await self._postgres.pool.fetchrow(_AVAILABLE, product_id)
        return None if record is None else int(record["available"])

    async def reserve_stock(self, order_id: str, items: Sequence[StockItem]) -> ReserveResult:
        """Атомарный резерв всех позиций под order_id, идемпотентно.

        Если под order_id уже есть резерв, он и возвращается — без проверки остатков и без
        сравнения с запрошенными позициями. При нехватке хотя бы одной позиции ничего не пишется.
        """
        product_ids = [item.product_id for item in items]
        async with self._postgres.pool.acquire() as connection, connection.transaction():
            # Повторы с одним order_id выполняются строго по очереди, даже с разными товарами
            await connection.execute("SELECT pg_advisory_xact_lock(hashtext($1))", order_id)
            existing = await connection.fetch(_ORDER_RESERVATIONS, order_id)
            if existing:
                return ReserveResult(
                    items=[StockItem(r["product_id"], r["quantity"]) for r in existing],
                    shortages=[],
                )
            quantities = {
                r["product_id"]: r["quantity"]
                for r in await connection.fetch(_LOCK_STOCKS, product_ids)
            }
            reserved = {
                r["product_id"]: r["reserved"]
                for r in await connection.fetch(_RESERVED, product_ids)
            }
            shortages = []
            for item in items:
                if item.product_id not in quantities:
                    shortages.append(StockShortage(item.product_id, item.quantity, None))
                    continue
                available = max(quantities[item.product_id] - reserved.get(item.product_id, 0), 0)
                if available < item.quantity:
                    shortages.append(StockShortage(item.product_id, item.quantity, available))
            if shortages:
                return ReserveResult(items=[], shortages=shortages)
            await connection.executemany(
                "INSERT INTO catalog.reservations (order_id, product_id, quantity) "
                "VALUES ($1, $2, $3)",
                [(order_id, item.product_id, item.quantity) for item in items],
            )
        return ReserveResult(items=list(items), shortages=[])

    async def release_stock(self, order_id: str) -> bool:
        """Снять резерв order_id; False — резерва не было (уже снят или не создавался)."""
        async with self._postgres.pool.acquire() as connection, connection.transaction():
            # Тот же замок, что у reserve_stock: снятие ждёт идущий резерв этого order_id,
            # иначе резерв, закоммиченный после DELETE, остался бы навсегда
            await connection.execute("SELECT pg_advisory_xact_lock(hashtext($1))", order_id)
            released = await connection.fetch(
                "DELETE FROM catalog.reservations WHERE order_id = $1 RETURNING product_id",
                order_id,
            )
        return bool(released)
