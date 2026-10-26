"""DomainEvents с фейковым RabbitMQ; OrderEvents против Redis из compose (make up) — без Redis
эти тесты пропускаются.

Адрес — env TEST_REDIS_URL, по умолчанию Redis из compose на localhost.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from order_service.domain_events import DomainEvents
from order_service.events import OrderEvents, channel, decode, encode
from order_service.models import OrderStatus, OrderStatusEvent, StatusChange
from order_service.settings import OrderSettings
from redis.exceptions import ConnectionError as RedisConnectionError
from stand_core.clients import Redis
from stand_core.events import ORDER_STATUS_CHANGED, OrderStatusChanged, parse_order_status_changed

from .fakes import FakeRabbit

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture
async def events(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[OrderEvents]:
    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    settings = OrderSettings()
    redis = Redis(settings)
    try:
        await redis.connect()
    except (OSError, RedisConnectionError) as exc:
        pytest.skip(f"Redis is not available ({exc}); run make up")
    try:
        yield OrderEvents(redis, settings)
    finally:
        await redis.disconnect()


def change(order_id: str, status: OrderStatus = OrderStatus.PAID) -> StatusChange:
    return StatusChange(order_id, status, datetime(2026, 10, 25, 12, 0, 0, 123456, tzinfo=UTC))


def order_status_event(status: OrderStatus = OrderStatus.PAID) -> OrderStatusEvent:
    return OrderStatusEvent(
        "o-1", "u-1", "buyer@example.com", status, datetime(2026, 10, 26, 12, 0, 1, tzinfo=UTC)
    )


async def test_publishes_order_status_changed(rabbit: FakeRabbit) -> None:
    await DomainEvents(_rabbit=rabbit).publish_quietly(order_status_event(OrderStatus.DELIVERED))

    [(routing_key, payload)] = rabbit.published
    assert routing_key == ORDER_STATUS_CHANGED
    assert parse_order_status_changed(payload) == OrderStatusChanged(
        order_id="o-1",
        user_id="u-1",
        status="DELIVERED",
        changed_at=datetime(2026, 10, 26, 12, 0, 1, tzinfo=UTC),
        email="buyer@example.com",
    )


async def test_publish_survives_broker_failure(rabbit: FakeRabbit) -> None:
    rabbit.error = RuntimeError("no broker")

    await DomainEvents(_rabbit=rabbit).publish_quietly(order_status_event())

    assert rabbit.published == []


async def test_publish_gives_up_on_hanging_broker(
    rabbit: FakeRabbit, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Robust-соединение ждёт переподключения: смена статуса не должна ждать вместе с ним."""

    async def hang(routing_key: str, payload: object) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(rabbit, "publish", hang)
    monkeypatch.setattr("order_service.domain_events.PUBLISH_TIMEOUT_S", 0.01)

    # Без таймаута в publish_quietly тест упадёт здесь, а не просто станет на 10 с дольше
    async with asyncio.timeout(1):
        await DomainEvents(_rabbit=rabbit).publish_quietly(order_status_event())


def test_encode_decode_round_trip() -> None:
    value = change("o-1", OrderStatus.HANDED_TO_COURIER)

    assert decode(encode(value)) == value
    assert channel("o-1") == "orders.status.o-1"


async def test_subscription_receives_changes_of_its_order_only(events: OrderEvents) -> None:
    order_id, other_id = str(uuid.uuid4()), str(uuid.uuid4())

    async with events.subscribe(order_id) as subscription:
        # Подписка уже действует: публикация сразу после входа в контекст не теряется
        await events.publish(change(other_id))
        await events.publish(change(order_id))
        await events.publish(change(order_id, OrderStatus.ASSEMBLING))

        first = await subscription.next(2)
        second = await subscription.next(2)
        nothing = await subscription.next(0.05)

    assert first == change(order_id)
    assert second == change(order_id, OrderStatus.ASSEMBLING)
    assert nothing is None


async def test_unsubscribed_after_context(events: OrderEvents) -> None:
    order_id = str(uuid.uuid4())

    async with events.subscribe(order_id):
        pass
    # Отписка — на сервере Redis: подписчиков канала не осталось
    await asyncio.sleep(0.05)
    counts = await events._redis.client.pubsub_numsub(channel(order_id))

    assert counts == [(channel(order_id), 0)]
