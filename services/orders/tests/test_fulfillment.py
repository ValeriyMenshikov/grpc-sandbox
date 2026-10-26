"""Имитация доставки: шаги статусов, публикация, отменённые заказы стоят на месте."""

import asyncio
from collections.abc import Callable
from datetime import timedelta

import pytest
from order_service.domain_events import DomainEvents
from order_service.fulfillment import Fulfillment
from order_service.models import OrderStatus, OrderStatusEvent
from order_service.settings import OrderSettings
from stand_core.events import ORDER_STATUS_CHANGED, parse_order_status_changed

from .fakes import FakeEvents, FakeRabbit, FakeRepository


async def run_until(fulfillment: Fulfillment, done: Callable[[], bool]) -> None:
    """Крутить фоновую задачу, пока не выполнится `done` (не дольше 5 с)."""
    task = asyncio.create_task(fulfillment.run())
    try:
        for _ in range(500):
            if done():
                return
            await asyncio.sleep(0.01)
        pytest.fail("fulfillment did not reach the expected state")
    finally:
        task.cancel()


@pytest.fixture
def fulfillment(
    repository: FakeRepository,
    events: FakeEvents,
    domain: DomainEvents,
    monkeypatch: pytest.MonkeyPatch,
) -> Fulfillment:
    monkeypatch.setenv("FULFILLMENT_STEP_MS", "10")
    return Fulfillment(repository, events, OrderSettings(), domain)


def test_step_and_poll_interval_from_settings(
    fulfillment: Fulfillment, repository: FakeRepository, events: FakeEvents, domain: DomainEvents
) -> None:
    assert fulfillment.step == timedelta(milliseconds=10)
    assert fulfillment.poll_interval_s == 0.01
    assert (
        Fulfillment(repository, events, OrderSettings.model_construct(), domain).poll_interval_s
        == 0.5
    )


async def test_advance_moves_active_orders_one_step_and_publishes(
    fulfillment: Fulfillment, repository: FakeRepository, events: FakeEvents
) -> None:
    created = repository.add(status=OrderStatus.CREATED)
    assembling = repository.add(status=OrderStatus.ASSEMBLING)
    cancelled = repository.add(status=OrderStatus.CANCELLED)
    delivered = repository.add(status=OrderStatus.DELIVERED)

    changes = await fulfillment.advance()

    assert [(change.order_id, change.status) for change in changes] == [
        (created.order_id, OrderStatus.PAID),
        (assembling.order_id, OrderStatus.HANDED_TO_COURIER),
    ]
    assert events.published == [change.change() for change in changes]
    assert repository.orders[cancelled.order_id] == cancelled
    assert repository.orders[delivered.order_id] == delivered


async def test_fulfillment_publishes_each_change(
    fulfillment: Fulfillment, repository: FakeRepository, rabbit: FakeRabbit
) -> None:
    order = repository.add(user_id="u-1")

    [change] = await fulfillment.advance()

    assert [routing_key for routing_key, _ in rabbit.published] == [ORDER_STATUS_CHANGED]
    [event] = [parse_order_status_changed(payload) for _, payload in rabbit.published]
    assert (event.order_id, event.user_id, event.status) == (order.order_id, "u-1", "PAID")
    assert event.changed_at == change.changed_at


async def test_broker_failure_keeps_redis_publication(
    fulfillment: Fulfillment, repository: FakeRepository, events: FakeEvents, rabbit: FakeRabbit
) -> None:
    repository.add()
    rabbit.error = ConnectionError("rabbitmq is down")

    changes = await fulfillment.advance()

    assert events.published == [change.change() for change in changes]


async def test_run_walks_order_to_delivered(
    fulfillment: Fulfillment, repository: FakeRepository, events: FakeEvents
) -> None:
    order = repository.add()
    cancelled = repository.add(status=OrderStatus.CANCELLED)

    await run_until(
        fulfillment, lambda: repository.orders[order.order_id].status is OrderStatus.DELIVERED
    )

    assert [change.status for change in events.published] == [
        OrderStatus.PAID,
        OrderStatus.ASSEMBLING,
        OrderStatus.HANDED_TO_COURIER,
        OrderStatus.DELIVERED,
    ]
    assert {change.order_id for change in events.published} == {order.order_id}
    assert repository.orders[cancelled.order_id] == cancelled


async def test_publish_failure_keeps_status_in_repository(
    fulfillment: Fulfillment, repository: FakeRepository, events: FakeEvents
) -> None:
    order = repository.add()
    events.error = ConnectionError("redis is down")

    changes = await fulfillment.advance()

    assert [change.status for change in changes] == [OrderStatus.PAID]
    assert repository.orders[order.order_id].status is OrderStatus.PAID


class FlakyRepository(FakeRepository):
    """Первый проход падает, как при недоступном Postgres."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def advance_due(self, step: timedelta) -> list[OrderStatusEvent]:
        self.calls += 1
        if self.calls == 1:
            raise OSError("postgres is down")
        return await super().advance_due(step)


async def test_run_survives_failed_pass(
    fulfillment: Fulfillment, events: FakeEvents, domain: DomainEvents
) -> None:
    repository = FlakyRepository()
    order = repository.add()
    flaky = Fulfillment(repository, events, OrderSettings(), domain)

    await run_until(
        flaky, lambda: repository.orders[order.order_id].status is not OrderStatus.CREATED
    )

    assert repository.calls >= 2
