"""SQL репозитория против Postgres из compose (make up) во временной базе.

Без доступного Postgres тесты пропускаются: unit-тесты хэндлеров обходятся без него.
Адрес — env TEST_POSTGRES_DSN, по умолчанию Postgres из compose на localhost.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import asyncpg
import pytest
from order_service.models import DELIVERY_STEPS, NEXT_STATUS, Order, OrderItem, OrderStatus
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


async def test_advance_due_walks_delivery_and_skips_cancelled(
    repository: OrderRepository, postgres: Postgres
) -> None:
    order = await create(repository)
    cancelled = await create(repository)
    await repository.cancel(cancelled.order_id)

    not_yet = await repository.advance_due(timedelta(hours=1))
    statuses = []
    for _ in range(5):
        statuses.append(
            [
                (change.order_id, change.status)
                for change in await repository.advance_due(timedelta())
            ]
        )
    found = await repository.get_order(order.order_id)

    assert not_yet == []
    assert statuses == [
        [(order.order_id, OrderStatus.PAID)],
        [(order.order_id, OrderStatus.ASSEMBLING)],
        [(order.order_id, OrderStatus.HANDED_TO_COURIER)],
        [(order.order_id, OrderStatus.DELIVERED)],
        [],
    ]
    assert found is not None
    assert found.status is OrderStatus.DELIVERED
    assert found.updated_at > order.updated_at
    still_cancelled = await repository.get_order(cancelled.order_id)
    assert still_cancelled is not None
    assert still_cancelled.status is OrderStatus.CANCELLED


async def test_advance_due_returns_changed_at_as_stored(repository: OrderRepository) -> None:
    order = await create(repository)

    [change] = await repository.advance_due(timedelta())
    found = await repository.get_order(order.order_id)

    assert found is not None
    assert change.changed_at == found.updated_at


async def test_status_history_records_each_change(repository: OrderRepository) -> None:
    order = await create(repository)
    assert [change.status for change in await repository.status_history(order.order_id)] == [
        OrderStatus.CREATED
    ]

    [event] = await repository.advance_due(timedelta())
    history = await repository.status_history(order.order_id)

    assert [change.status for change in history] == [OrderStatus.CREATED, OrderStatus.PAID]
    assert history[0].changed_at == order.created_at
    assert history[-1].changed_at == event.changed_at
    assert await repository.status_history("missing") == []


async def test_cancel_records_history(repository: OrderRepository) -> None:
    order = await create(repository)

    cancelled = await repository.cancel(order.order_id)
    history = await repository.status_history(order.order_id)

    assert cancelled is not None
    assert [change.status for change in history] == [OrderStatus.CREATED, OrderStatus.CANCELLED]
    assert history[-1].changed_at == cancelled.updated_at
    # Неудачная повторная отмена историю не трогает
    assert await repository.cancel(order.order_id) is None
    assert len(await repository.status_history(order.order_id)) == 2


async def test_advance_due_returns_user_id(repository: OrderRepository) -> None:
    order = await create(repository, user_id="u-1")

    events = await repository.advance_due(timedelta())

    assert [(event.order_id, event.user_id, event.email) for event in events] == [
        (order.order_id, "u-1", "")
    ]


def test_delivery_steps_match_next_status() -> None:
    assert DELIVERY_STEPS[0] is OrderStatus.CREATED
    assert DELIVERY_STEPS[-1] is OrderStatus.DELIVERED
    assert OrderStatus.CANCELLED not in DELIVERY_STEPS
    assert all(
        NEXT_STATUS[step] is DELIVERY_STEPS[i + 1] for i, step in enumerate(DELIVERY_STEPS[:-1])
    )
