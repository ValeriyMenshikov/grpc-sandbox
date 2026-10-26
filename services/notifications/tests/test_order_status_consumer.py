"""Consumer order.status_changed: письмо только на DELIVERED, SKIPPED без адреса, dead-letter."""

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiosmtplib
import pytest
from notification_service.models import NotificationStatus
from notification_service.order_status_consumer import OrderStatusConsumer
from notification_service.settings import NotificationSettings
from stand_core.events import (
    ORDER_STATUS_CHANGED,
    OrderStatusChanged,
    order_status_changed_payload,
)

from .fakes import FakeMailer, FakeQueueIterator, FakeRepository, message


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


def event_body(status: str = "DELIVERED", email: str = "buyer@example.com") -> bytes:
    event = OrderStatusChanged(
        order_id="order-1",
        user_id="user-1",
        status=status,
        changed_at=datetime(2026, 10, 26, 12, 0, tzinfo=UTC),
        email=email,
        request_id="req-1",
    )
    return json.dumps(order_status_changed_payload(event)).encode()


def consumer(mailer: FakeMailer, repository: FakeRepository) -> OrderStatusConsumer:
    return OrderStatusConsumer(MagicMock(), mailer, repository, NotificationSettings())


async def test_sends_email_on_delivered(mailer: FakeMailer, repository: FakeRepository) -> None:
    incoming = message(event_body())

    await consumer(mailer, repository).handle(incoming)

    [(to_email, content)] = mailer.sent
    assert (to_email, content.subject) == ("buyer@example.com", "Заказ доставлен")
    assert "order-1" in content.body
    incoming.ack.assert_awaited_once_with()
    incoming.nack.assert_not_awaited()
    [notification] = repository.notifications
    assert notification.status is NotificationStatus.SENT
    assert (notification.to_email, notification.subject) == ("buyer@example.com", content.subject)


@pytest.mark.parametrize(
    "status", ["CREATED", "PAID", "ASSEMBLING", "HANDED_TO_COURIER", "CANCELLED"]
)
async def test_skips_other_statuses(
    mailer: FakeMailer, repository: FakeRepository, status: str
) -> None:
    incoming = message(event_body(status=status))

    await consumer(mailer, repository).handle(incoming)

    assert mailer.sent == []
    assert repository.notifications == []
    incoming.ack.assert_awaited_once_with()
    incoming.nack.assert_not_awaited()


async def test_empty_email_is_skipped_not_dead_lettered(
    mailer: FakeMailer, repository: FakeRepository
) -> None:
    incoming = message(event_body(email=""))

    await consumer(mailer, repository).handle(incoming)

    assert mailer.sent == []
    [notification] = repository.notifications
    assert notification.status is NotificationStatus.SKIPPED
    assert (notification.to_email, notification.subject) == ("", "Заказ доставлен")
    assert notification.error == "order has no buyer email"
    incoming.ack.assert_awaited_once_with()
    incoming.nack.assert_not_awaited()


@pytest.mark.parametrize(
    "body",
    [
        event_body(status="TELEPORTED"),
        b"not json",
        json.dumps({"order_id": "order-1"}).encode(),
    ],
    ids=["unknown-status", "not-json", "missing-fields"],
)
async def test_invalid_event_goes_to_dead_letter(
    mailer: FakeMailer, repository: FakeRepository, body: bytes
) -> None:
    incoming = message(body)

    await consumer(mailer, repository).handle(incoming)

    assert mailer.sent == []
    incoming.nack.assert_awaited_once_with(requeue=False)
    incoming.ack.assert_not_awaited()
    [notification] = repository.notifications
    assert notification.status is NotificationStatus.FAILED
    assert notification.error


async def test_unknown_status_error_names_status(
    mailer: FakeMailer, repository: FakeRepository
) -> None:
    await consumer(mailer, repository).handle(message(event_body(status="TELEPORTED")))

    assert "TELEPORTED" in repository.notifications[0].error


async def test_smtp_error_is_dead_lettered(repository: FakeRepository) -> None:
    incoming = message(event_body())

    await consumer(FakeMailer(aiosmtplib.SMTPConnectError("refused")), repository).handle(incoming)

    incoming.nack.assert_awaited_once_with(requeue=False)
    incoming.ack.assert_not_awaited()
    [notification] = repository.notifications
    assert notification.status is NotificationStatus.FAILED
    assert notification.to_email == "buyer@example.com"
    assert "refused" in notification.error


async def test_journal_failure_does_not_block_skip_ack(
    monkeypatch: pytest.MonkeyPatch, mailer: FakeMailer, repository: FakeRepository
) -> None:
    monkeypatch.setattr(repository, "record", AsyncMock(side_effect=OSError("postgres is down")))
    incoming = message(event_body(email=""))

    await consumer(mailer, repository).handle(incoming)

    incoming.ack.assert_awaited_once_with()


async def test_run_survives_bad_message(mailer: FakeMailer, repository: FakeRepository) -> None:
    broken, good = message(b"\xff"), message(event_body())
    order_consumer = consumer(mailer, repository)
    queue = MagicMock()
    queue.iterator.return_value = FakeQueueIterator([broken, good])
    order_consumer._queue = queue

    with pytest.raises(RuntimeError, match="order status queue consumption stopped"):
        await order_consumer.run()

    broken.nack.assert_awaited_once_with(requeue=False)
    good.ack.assert_awaited_once_with()


async def test_connect_declares_own_queue_and_dead_letter(repository: FakeRepository) -> None:
    rabbit = MagicMock()
    rabbit.open = AsyncMock()
    channel = rabbit.channel
    channel.set_qos = AsyncMock()
    dead_exchange = MagicMock()
    channel.declare_exchange = AsyncMock(return_value=dead_exchange)
    dead_queue, queue = MagicMock(), MagicMock()
    dead_queue.bind = AsyncMock()
    queue.bind = AsyncMock()
    channel.declare_queue = AsyncMock(side_effect=[dead_queue, queue])
    order_consumer = OrderStatusConsumer(rabbit, FakeMailer(), repository, NotificationSettings())

    with pytest.raises(RuntimeError, match="OrderStatusConsumer is not connected"):
        _ = order_consumer.queue
    await order_consumer.connect()

    rabbit.open.assert_awaited_once_with()
    channel.declare_exchange.assert_awaited_once_with(
        "notifications.order_status.dead", "fanout", durable=True
    )
    assert channel.declare_queue.await_args_list[0].args == ("notifications.order_status.dead",)
    dead_queue.bind.assert_awaited_once_with(dead_exchange)
    main_call: Any = channel.declare_queue.await_args_list[1]
    assert main_call.args == ("notifications.order_status",)
    assert main_call.kwargs == {
        "durable": True,
        "arguments": {"x-dead-letter-exchange": "notifications.order_status.dead"},
    }
    queue.bind.assert_awaited_once_with(rabbit.exchange, routing_key=ORDER_STATUS_CHANGED)
    assert order_consumer.queue is queue
