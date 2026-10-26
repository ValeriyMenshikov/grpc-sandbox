"""Consumer order.status_changed: идемпотентная проекция, dead-letter, переподключение."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from stand_core.events import ORDER_STATUS_CHANGED, OrderStatusChanged, order_status_changed_payload
from support_service.models import OrderEvent
from support_service.order_status_consumer import OrderStatusConsumer
from support_service.settings import SupportSettings

from .fakes import FakeRepository, fake_rabbit, rabbit_message

CHANGED_AT = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
WAIT_S = 2.0
POLL_S = 0.005


def event_body(order_id: str = "o-1", status: str = "PAID") -> bytes:
    event = OrderStatusChanged(
        order_id=order_id, user_id="u-1", status=status, changed_at=CHANGED_AT, request_id="req-1"
    )
    return json.dumps(order_status_changed_payload(event)).encode()


def consumer(repository: FakeRepository, rabbit: MagicMock | None = None) -> OrderStatusConsumer:
    return OrderStatusConsumer(rabbit or fake_rabbit(), repository, SupportSettings())


async def wait_for(condition: Callable[[], bool]) -> None:
    for _ in range(int(WAIT_S / POLL_S)):
        if condition():
            return
        await asyncio.sleep(POLL_S)
    raise AssertionError(f"condition is not met in {WAIT_S}s")


async def test_consumer_records_projection(repository: FakeRepository) -> None:
    incoming = rabbit_message(event_body(status="PAID"))

    await consumer(repository).handle(incoming)

    assert repository.events["o-1"] == [OrderEvent("o-1", "PAID", CHANGED_AT)]
    incoming.ack.assert_awaited_once_with()
    incoming.nack.assert_not_awaited()


async def test_redelivered_event_is_acked_without_duplicate(repository: FakeRepository) -> None:
    first, again = rabbit_message(event_body()), rabbit_message(event_body())

    await consumer(repository).handle(first)
    await consumer(repository).handle(again)

    assert [event.status for event in repository.events["o-1"]] == ["PAID"]
    again.ack.assert_awaited_once_with()


@pytest.mark.parametrize("body", [b"not json", b"{}", event_body(status="LOST_IN_SPACE")])
async def test_invalid_event_is_dead_lettered(repository: FakeRepository, body: bytes) -> None:
    incoming = rabbit_message(body)

    await consumer(repository).handle(incoming)

    assert repository.events == {}
    incoming.nack.assert_awaited_once_with(requeue=False)
    incoming.ack.assert_not_awaited()


async def test_postgres_error_leaves_message_unacked(repository: FakeRepository) -> None:
    repository.event_error = ConnectionError("postgres is down")
    incoming = rabbit_message(event_body())

    with pytest.raises(ConnectionError):
        await consumer(repository).handle(incoming)

    incoming.ack.assert_not_awaited()
    incoming.nack.assert_not_awaited()


async def test_declare_binds_queue_with_dead_letter(repository: FakeRepository) -> None:
    rabbit = fake_rabbit()
    expected = rabbit.queue

    queue = await consumer(repository, rabbit).declare()

    expected.bind.assert_any_await(rabbit.exchange, routing_key=ORDER_STATUS_CHANGED)
    assert queue is expected
    declared = rabbit.channel.declare_queue.await_args_list
    assert [call.args[0] for call in declared] == [
        "support.order_events.dead",
        "support.order_events",
    ]
    assert declared[1].kwargs["arguments"] == {
        "x-dead-letter-exchange": "support.order_events.dead"
    }


@pytest.mark.usefixtures("fast_reconnect")
async def test_consumer_reconnects_after_broker_failure(repository: FakeRepository) -> None:
    """Первые попытки падают, следующая работает: run() не умирает насовсем."""
    rabbit = fake_rabbit(rabbit_message(event_body()), open_errors=2)
    task = asyncio.create_task(consumer(repository, rabbit).run())
    try:
        await wait_for(lambda: "o-1" in repository.events)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert rabbit.open.await_count >= 3
    assert rabbit.disconnect.await_count >= 2
    assert [event.status for event in repository.events["o-1"]] == ["PAID"]


@pytest.mark.usefixtures("fast_reconnect")
async def test_consumer_keeps_retrying_without_broker(repository: FakeRepository) -> None:
    rabbit = fake_rabbit(open_errors=1_000)
    task = asyncio.create_task(consumer(repository, rabbit).run())
    try:
        await wait_for(lambda: rabbit.open.await_count >= 3)
        assert not task.done()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
