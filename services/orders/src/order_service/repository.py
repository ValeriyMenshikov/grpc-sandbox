"""Репозиторий заказов поверх Postgres (схема `orders`, см. schema.sql)."""

from collections.abc import Sequence
from pathlib import Path

import asyncpg
from nuke_di import Client
from stand_core.clients import Postgres

from order_service.models import CANCELLABLE_STATUSES, Order, OrderItem, OrderStatus

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_ORDER_COLUMNS = "order_id, user_id, status, created_at, updated_at"

_INSERT_ORDER = f"""
INSERT INTO orders.orders (order_id, user_id, status)
VALUES ($1, $2, 'CREATED')
RETURNING {_ORDER_COLUMNS}
"""

_INSERT_ITEMS = """
INSERT INTO orders.order_items (order_id, position, product_id, name, quantity, price_kopecks)
SELECT $1, position, product_id, name, quantity, price_kopecks
FROM unnest($2::text[], $3::text[], $4::bigint[], $5::bigint[])
    WITH ORDINALITY AS item (product_id, name, quantity, price_kopecks, position)
"""

_ITEMS = """
SELECT order_id, product_id, name, quantity, price_kopecks
FROM orders.order_items
WHERE order_id = ANY($1::text[])
ORDER BY order_id, position
"""

# Статус проверяется в том же UPDATE: отмена не обгонит передачу курьеру
_CANCEL = f"""
UPDATE orders.orders SET status = 'CANCELLED', updated_at = now()
WHERE order_id = $1 AND status = ANY($2::text[])
RETURNING {_ORDER_COLUMNS}
"""


def _order(record: asyncpg.Record, items: Sequence[OrderItem]) -> Order:
    return Order(
        order_id=record["order_id"],
        user_id=record["user_id"],
        status=OrderStatus(record["status"]),
        items=tuple(items),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


class OrderRepository(Client):
    def __init__(self, postgres: Postgres) -> None:
        self._postgres = postgres

    async def connect(self) -> None:
        await self._postgres.apply_schema(SCHEMA_PATH)

    async def create_order(self, order_id: str, user_id: str, items: Sequence[OrderItem]) -> Order:
        """Новый заказ в статусе CREATED с позициями — одной транзакцией."""
        async with self._postgres.pool.acquire() as connection, connection.transaction():
            record = await connection.fetchrow(_INSERT_ORDER, order_id, user_id)
            await connection.execute(
                _INSERT_ITEMS,
                order_id,
                [item.product_id for item in items],
                [item.name for item in items],
                [item.quantity for item in items],
                [item.price_kopecks for item in items],
            )
        assert record is not None
        return _order(record, items)

    async def get_order(self, order_id: str) -> Order | None:
        record = await self._postgres.pool.fetchrow(
            f"SELECT {_ORDER_COLUMNS} FROM orders.orders WHERE order_id = $1", order_id
        )
        if record is None:
            return None
        return (await self._with_items([record]))[0]

    async def list_orders(
        self, user_id: str, status: OrderStatus | None, offset: int, limit: int
    ) -> list[Order]:
        """Заказы пользователя, новые первыми; `status` None — все статусы."""
        records = await self._postgres.pool.fetch(
            f"SELECT {_ORDER_COLUMNS} FROM orders.orders "
            "WHERE user_id = $1 AND ($2::text IS NULL OR status = $2) "
            "ORDER BY created_at DESC, order_id DESC OFFSET $3 LIMIT $4",
            user_id,
            None if status is None else status.value,
            offset,
            limit,
        )
        return await self._with_items(records)

    async def cancel(self, order_id: str) -> Order | None:
        """Отменить заказ, если он ещё не передан курьеру; None — отменить нельзя или нет заказа."""
        record = await self._postgres.pool.fetchrow(
            _CANCEL, order_id, [status.value for status in CANCELLABLE_STATUSES]
        )
        if record is None:
            return None
        return (await self._with_items([record]))[0]

    async def _with_items(self, records: Sequence[asyncpg.Record]) -> list[Order]:
        if not records:
            return []
        rows = await self._postgres.pool.fetch(_ITEMS, [record["order_id"] for record in records])
        items: dict[str, list[OrderItem]] = {record["order_id"]: [] for record in records}
        for row in rows:
            items[row["order_id"]].append(
                OrderItem(row["product_id"], row["name"], row["quantity"], row["price_kopecks"])
            )
        return [_order(record, items[record["order_id"]]) for record in records]
