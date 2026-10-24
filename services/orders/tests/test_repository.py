"""SQL репозитория против Postgres из compose (make up) во временной базе.

Без доступного Postgres тесты пропускаются: unit-тесты хэндлеров обходятся без него.
Адрес — env TEST_POSTGRES_DSN, по умолчанию Postgres из compose на localhost.
"""

import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
from order_service.models import Order, OrderItem, OrderStatus
from order_service.repository import OrderRepository
from order_service.settings import OrderSettings
from stand_core.clients import Postgres

ADMIN_DSN = os.environ.get("TEST_POSTGRES_DSN", "postgresql://stand:stand@localhost:5432/stand")
ITEMS = [OrderItem("p-2", "Книга", 1, 500_00), OrderItem("p-1", "Наушники", 2, 1_999_90)]


@pytest.fixture
async def postgres(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Postgres]:
    try:
        admin = await asyncpg.connect(ADMIN_DSN, timeout=2)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres is not available ({exc}); run make up")
    database = f"orders_test_{uuid.uuid4().hex[:12]}"
    await admin.execute(f'CREATE DATABASE "{database}"')
    monkeypatch.setenv("POSTGRES_DSN", f"{ADMIN_DSN.rsplit('/', 1)[0]}/{database}")
    client = Postgres(OrderSettings())
    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.close()


@pytest.fixture
async def repository(postgres: Postgres) -> OrderRepository:
    repository = OrderRepository(postgres)
    await repository.connect()
    # Схема идемпотентна: второй connect() не падает
    await repository.connect()
    return repository


async def create(repository: OrderRepository, user_id: str = "u1") -> Order:
    return await repository.create_order(str(uuid.uuid4()), user_id, ITEMS)


async def test_create_and_get_keeps_item_order(repository: OrderRepository) -> None:
    created = await create(repository)

    found = await repository.get_order(created.order_id)

    assert found == created
    assert found.status is OrderStatus.CREATED
    assert found.items == tuple(ITEMS)
    assert found.total_kopecks == 500_00 + 2 * 1_999_90
    assert await repository.get_order("missing") is None


async def test_list_newest_first_by_user_and_status(
    repository: OrderRepository, postgres: Postgres
) -> None:
    first = await create(repository)
    second = await create(repository)
    await create(repository, user_id="u2")
    await postgres.pool.execute(
        "UPDATE orders.orders SET created_at = now() + interval '1 minute' WHERE order_id = $1",
        first.order_id,
    )
    await repository.cancel(second.order_id)

    everything = await repository.list_orders("u1", None, 0, 10)
    page = await repository.list_orders("u1", None, 1, 1)
    cancelled = await repository.list_orders("u1", OrderStatus.CANCELLED, 0, 10)

    assert [o.order_id for o in everything] == [first.order_id, second.order_id]
    assert [o.order_id for o in page] == [second.order_id]
    assert [o.order_id for o in cancelled] == [second.order_id]
    assert cancelled[0].items == tuple(ITEMS)


async def test_cancel_only_before_courier(repository: OrderRepository, postgres: Postgres) -> None:
    order = await create(repository)
    handed = await create(repository)
    await postgres.pool.execute(
        "UPDATE orders.orders SET status = 'HANDED_TO_COURIER' WHERE order_id = $1",
        handed.order_id,
    )

    cancelled = await repository.cancel(order.order_id)

    assert cancelled is not None
    assert cancelled.status is OrderStatus.CANCELLED
    assert cancelled.updated_at >= order.updated_at
    assert await repository.cancel(order.order_id) is None
    assert await repository.cancel(handed.order_id) is None
    assert await repository.cancel("missing") is None
