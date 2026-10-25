"""Consumer очереди писем: ack после отправки, nack без requeue при ошибке, журнал попыток.

Последний тест — против RabbitMQ и Mailpit из compose (make up), без них пропускается.
Адреса — env TEST_RABBITMQ_URL/TEST_SMTP_HOST/TEST_SMTP_PORT/TEST_MAILPIT_URL, по умолчанию
compose на localhost.
"""

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aio_pika
import aiosmtplib
import httpx
import pytest
from notification_service.consumer import PREFETCH_COUNT, EmailConsumer
from notification_service.mailer import Mailer
from notification_service.models import NotificationStatus
from notification_service.settings import NotificationSettings
from stand_core.clients import Rabbit
from stand_core.events import (
    USER_EMAIL_CONFIRMATION_REQUESTED,
    EmailConfirmationRequested,
    email_confirmation_payload,
)
from stand_core.settings import Settings

from .fakes import FakeMailer, FakeRepository

RABBITMQ_URL = os.environ.get("TEST_RABBITMQ_URL", "amqp://stand:stand@localhost:5672/")
SMTP_HOST = os.environ.get("TEST_SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("TEST_SMTP_PORT", "1025"))
MAILPIT_URL = os.environ.get("TEST_MAILPIT_URL", "http://localhost:8025/mail")

EVENT = EmailConfirmationRequested(
    email="buyer@example.com",
    code="123456",
    display_name="Покупатель",
    ttl_s=900,
    request_id="req-1",
)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAND_API_KEY", "test-key")


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


def message(body: bytes, correlation_id: str | None = "req-from-header") -> MagicMock:
    """Входящее сообщение aio-pika: тело, заголовки и ack/nack."""
    incoming = MagicMock()
    incoming.body = body
    incoming.message_id = uuid.uuid4().hex
    incoming.correlation_id = correlation_id
    incoming.ack = AsyncMock()
    incoming.nack = AsyncMock()
    return incoming


def event_body(event: EmailConfirmationRequested = EVENT) -> bytes:
    return json.dumps(email_confirmation_payload(event)).encode()


def consumer(mailer: FakeMailer, repository: FakeRepository) -> EmailConsumer:
    return EmailConsumer(MagicMock(), mailer, repository, NotificationSettings())


async def test_sent_email_is_acked_and_recorded(repository: FakeRepository) -> None:
    mailer = FakeMailer()
    incoming = message(event_body())

    await consumer(mailer, repository).handle(incoming)

    [(to_email, content)] = mailer.sent
    assert to_email == "buyer@example.com"
    assert "123456" in content.body
    incoming.ack.assert_awaited_once_with()
    incoming.nack.assert_not_awaited()
    [notification] = repository.notifications
    assert notification.status is NotificationStatus.SENT
    assert notification.to_email == "buyer@example.com"
    assert notification.subject == content.subject
    assert notification.error == ""


async def test_smtp_error_is_nacked_without_requeue_and_recorded(
    repository: FakeRepository,
) -> None:
    mailer = FakeMailer(aiosmtplib.SMTPConnectError("connection refused"))
    incoming = message(event_body())

    await consumer(mailer, repository).handle(incoming)

    incoming.nack.assert_awaited_once_with(requeue=False)
    incoming.ack.assert_not_awaited()
    [notification] = repository.notifications
    assert notification.status is NotificationStatus.FAILED
    assert notification.to_email == "buyer@example.com"
    assert notification.subject == "Код подтверждения: 123456"
    assert "connection refused" in notification.error


async def test_error_without_message_records_exception_type(repository: FakeRepository) -> None:
    incoming = message(event_body())

    await consumer(FakeMailer(TimeoutError()), repository).handle(incoming)

    incoming.nack.assert_awaited_once_with(requeue=False)
    assert repository.notifications[0].error == "TimeoutError"


@pytest.mark.parametrize(
    "body",
    [b"not json", b"[1, 2]", json.dumps({"email": "a@example.com"}).encode()],
    ids=["not-json", "not-object", "missing-fields"],
)
async def test_invalid_body_is_nacked_without_requeue(
    repository: FakeRepository, body: bytes
) -> None:
    mailer = FakeMailer()
    incoming = message(body)

    await consumer(mailer, repository).handle(incoming)

    assert mailer.sent == []
    incoming.nack.assert_awaited_once_with(requeue=False)
    incoming.ack.assert_not_awaited()
    [notification] = repository.notifications
    assert notification.status is NotificationStatus.FAILED
    assert notification.to_email == ""
    assert notification.error


async def test_journal_failure_does_not_block_ack(
    monkeypatch: pytest.MonkeyPatch, repository: FakeRepository
) -> None:
    monkeypatch.setattr(repository, "record", AsyncMock(side_effect=OSError("postgres is down")))
    incoming = message(event_body())

    await consumer(FakeMailer(), repository).handle(incoming)

    incoming.ack.assert_awaited_once_with()


class FakeQueueIterator:
    """`queue.iterator()`: асинхронный контекст и итератор по заранее заданным сообщениям."""

    def __init__(self, messages: list[MagicMock]) -> None:
        self.messages = messages

    async def __aenter__(self) -> AsyncIterator[MagicMock]:
        return self._iterate()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        pass

    async def _iterate(self) -> AsyncIterator[MagicMock]:
        for incoming in self.messages:
            yield incoming


async def test_run_survives_bad_message(repository: FakeRepository) -> None:
    mailer = FakeMailer()
    broken, good = message(b"\xff"), message(event_body())
    email_consumer = consumer(mailer, repository)
    queue = MagicMock()
    queue.iterator.return_value = FakeQueueIterator([broken, good])
    email_consumer._queue = queue

    await email_consumer.run()

    broken.nack.assert_awaited_once_with(requeue=False)
    good.ack.assert_awaited_once_with()
    assert [n.status for n in repository.notifications] == [
        NotificationStatus.FAILED,
        NotificationStatus.SENT,
    ]


async def test_connect_declares_queues_with_dead_letter(repository: FakeRepository) -> None:
    rabbit = MagicMock()
    channel = rabbit.channel
    channel.set_qos = AsyncMock()
    dead_exchange = MagicMock()
    channel.declare_exchange = AsyncMock(return_value=dead_exchange)
    dead_queue, queue = MagicMock(), MagicMock()
    dead_queue.bind = AsyncMock()
    queue.bind = AsyncMock()
    channel.declare_queue = AsyncMock(side_effect=[dead_queue, queue])
    email_consumer = EmailConsumer(rabbit, FakeMailer(), repository, NotificationSettings())

    with pytest.raises(RuntimeError, match="EmailConsumer is not connected"):
        _ = email_consumer.queue
    await email_consumer.connect()

    channel.set_qos.assert_awaited_once_with(prefetch_count=PREFETCH_COUNT)
    channel.declare_exchange.assert_awaited_once_with("stand.events.dead", "fanout", durable=True)
    assert channel.declare_queue.await_args_list[0].args == ("notifications.email.dead",)
    dead_queue.bind.assert_awaited_once_with(dead_exchange)
    main_call = channel.declare_queue.await_args_list[1]
    assert main_call.args == ("notifications.email",)
    assert main_call.kwargs == {
        "durable": True,
        "arguments": {"x-dead-letter-exchange": "stand.events.dead"},
    }
    queue.bind.assert_awaited_once_with(
        rabbit.exchange, routing_key=USER_EMAIL_CONFIRMATION_REQUESTED
    )
    assert email_consumer.queue is queue


async def wait_for_email(http: httpx.AsyncClient, to_email: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for _ in range(50):
        found = await http.get("/api/v1/search", params={"query": f"to:{to_email}"})
        found.raise_for_status()
        messages = found.json()["messages"]
        if messages:
            break
        await asyncio.sleep(0.1)
    return messages


async def test_published_event_becomes_email(
    monkeypatch: pytest.MonkeyPatch, repository: FakeRepository
) -> None:
    async with httpx.AsyncClient(base_url=MAILPIT_URL, timeout=2) as http:
        try:
            (await http.get("/api/v1/info")).raise_for_status()
        except httpx.HTTPError as exc:
            pytest.skip(f"Mailpit is not available ({exc}); run make up")
        suffix = uuid.uuid4().hex[:12]
        monkeypatch.setenv("RABBITMQ_URL", RABBITMQ_URL)
        monkeypatch.setenv("SMTP_HOST", SMTP_HOST)
        monkeypatch.setenv("SMTP_PORT", str(SMTP_PORT))
        # Свои очереди и dead-letter: не отнимать сообщения у notification-service из compose
        monkeypatch.setenv("EMAIL_QUEUE", f"test.notifications.email.{suffix}")
        monkeypatch.setenv("DEAD_LETTER_EXCHANGE", f"test.stand.events.dead.{suffix}")
        monkeypatch.setenv("DEAD_LETTER_QUEUE", f"test.notifications.email.dead.{suffix}")
        settings = NotificationSettings()
        rabbit = Rabbit(Settings())
        try:
            await rabbit.connect()
        except (OSError, aio_pika.exceptions.AMQPError, RuntimeError) as exc:
            pytest.skip(f"RabbitMQ is not available ({exc}); run make up")
        email_consumer = EmailConsumer(rabbit, Mailer(settings), repository, settings)
        task: asyncio.Task[None] | None = None
        try:
            await email_consumer.connect()
            task = asyncio.create_task(email_consumer.run())
            # Уникальный адрес: ящик общий со стендом и smoke, чистить его тест не должен
            to_email = f"consumer-test-{suffix}@example.com"
            event = EmailConfirmationRequested(
                email=to_email, code="654321", display_name="Тест", ttl_s=600
            )
            await rabbit.publish(
                USER_EMAIL_CONFIRMATION_REQUESTED, email_confirmation_payload(event)
            )
            await rabbit.publish(USER_EMAIL_CONFIRMATION_REQUESTED, {"broken": True})

            messages = await wait_for_email(http, to_email)
            assert len(messages) == 1
            assert messages[0]["Subject"] == "Код подтверждения: 654321"
            await http.request("DELETE", "/api/v1/messages", json={"IDs": [messages[0]["ID"]]})

            # Битое событие — в dead-letter, а не обратно в очередь
            dead_queue = await rabbit.channel.get_queue(settings.dead_letter_queue)
            dead = None
            for _ in range(50):
                dead = await dead_queue.get(no_ack=True, fail=False)
                if dead is not None:
                    break
                await asyncio.sleep(0.1)
            assert dead is not None
            assert json.loads(dead.body) == {"broken": True}
            assert {n.status for n in repository.notifications} == {
                NotificationStatus.SENT,
                NotificationStatus.FAILED,
            }
        finally:
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            channel = rabbit.channel
            await channel.queue_delete(settings.email_queue)
            await channel.queue_delete(settings.dead_letter_queue)
            await channel.exchange_delete(settings.dead_letter_exchange)
            await rabbit.disconnect()


async def test_run_survives_ack_failure(repository: FakeRepository) -> None:
    lost, good = message(event_body()), message(event_body())
    lost.ack.side_effect = RuntimeError("channel closed")
    email_consumer = consumer(FakeMailer(), repository)
    queue = MagicMock()
    queue.iterator.return_value = FakeQueueIterator([lost, good])
    email_consumer._queue = queue

    await email_consumer.run()

    good.ack.assert_awaited_once_with()
