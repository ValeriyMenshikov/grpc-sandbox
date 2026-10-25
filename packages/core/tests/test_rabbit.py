"""Клиент Rabbit: aio-pika замокан; отдельный тест — против RabbitMQ из compose (skip без него).

Адрес живого брокера — env TEST_RABBITMQ_URL, по умолчанию RabbitMQ из compose на localhost.
"""

import json
import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aio_pika
import pytest
from stand_core.clients import Rabbit
from stand_core.grpc.context import reset_request_id, set_request_id
from stand_core.settings import Settings
from structlog.testing import capture_logs

LIVE_URL = os.environ.get("TEST_RABBITMQ_URL", "amqp://stand:stand@localhost:5672/")


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("STAND_API_KEY", "key")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://user:pass@broker:5672/")
    monkeypatch.delenv("EVENTS_EXCHANGE", raising=False)
    return Settings()


@pytest.fixture
def connection(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Подменяет aio_pika.connect_robust: соединение → канал → exchange."""
    exchange = MagicMock()
    exchange.publish = AsyncMock()
    channel = MagicMock()
    channel.declare_exchange = AsyncMock(return_value=exchange)
    conn = MagicMock()
    conn.channel = AsyncMock(return_value=channel)
    conn.close = AsyncMock()
    monkeypatch.setattr(aio_pika, "connect_robust", AsyncMock(return_value=conn))
    return conn


def test_exchange_before_connect_raises(settings: Settings) -> None:
    rabbit = Rabbit(settings)

    with pytest.raises(RuntimeError, match="Rabbit is not connected"):
        _ = rabbit.exchange
    with pytest.raises(RuntimeError, match="Rabbit is not connected"):
        _ = rabbit.channel


async def test_publish_before_connect_opens_connection(
    settings: Settings, connection: MagicMock
) -> None:
    rabbit = Rabbit(settings)

    await rabbit.publish("any.key", {})

    publish: Any = rabbit.exchange.publish
    publish.assert_awaited_once()


async def test_publish_without_broker_raises(settings: Settings) -> None:
    connect_robust = AsyncMock(side_effect=ConnectionError("refused"))
    with (
        patch.object(aio_pika, "connect_robust", connect_robust),
        pytest.raises(ConnectionError, match="refused"),
    ):
        await Rabbit(settings).publish("any.key", {})


async def test_open_requires_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAND_API_KEY", "key")
    monkeypatch.delenv("RABBITMQ_URL", raising=False)

    with pytest.raises(RuntimeError, match="RABBITMQ_URL"):
        await Rabbit(Settings()).open()


async def test_connect_without_broker_only_logs(settings: Settings) -> None:
    rabbit = Rabbit(settings)
    connect_robust = AsyncMock(side_effect=ConnectionError("refused"))

    with patch.object(aio_pika, "connect_robust", connect_robust), capture_logs() as logs:
        await rabbit.connect()

    assert logs == [{"event": "rabbit.connect_failed", "error": "refused", "log_level": "warning"}]
    with pytest.raises(RuntimeError, match="not connected"):
        _ = rabbit.exchange


async def test_open_is_idempotent(settings: Settings, connection: MagicMock) -> None:
    rabbit = Rabbit(settings)

    await rabbit.connect()
    await rabbit.open()

    connect_robust: Any = aio_pika.connect_robust
    connect_robust.assert_awaited_once()


async def test_connect_declares_durable_topic_exchange(
    settings: Settings, connection: MagicMock
) -> None:
    rabbit = Rabbit(settings)
    await rabbit.connect()

    connect_robust: Any = aio_pika.connect_robust
    connect_robust.assert_awaited_once_with(
        "amqp://user:pass@broker:5672/", timeout=settings.connect_timeout_seconds
    )
    connection.channel.assert_awaited_once_with(on_return_raises=True)
    channel = connection.channel.return_value
    channel.declare_exchange.assert_awaited_once_with(
        "stand.events", aio_pika.ExchangeType.TOPIC, durable=True
    )
    # Сначала exchange: `is` сужает тип мока до AbstractChannel
    assert rabbit.exchange is channel.declare_exchange.return_value
    assert rabbit.channel is channel


async def test_connect_closes_connection_when_declare_fails(
    settings: Settings, connection: MagicMock
) -> None:
    connection.channel.return_value.declare_exchange.side_effect = OSError("boom")

    rabbit = Rabbit(settings)
    with pytest.raises(OSError, match="boom"):
        await rabbit.open()

    connection.close.assert_awaited_once()
    with pytest.raises(RuntimeError, match="not connected"):
        _ = rabbit.exchange


async def test_publish_sends_persistent_json(settings: Settings, connection: MagicMock) -> None:
    rabbit = Rabbit(settings)
    await rabbit.connect()

    token = set_request_id("req-42")
    try:
        await rabbit.publish("user.email_confirmation_requested", {"email": "a@b.c", "n": "Юля"})
    finally:
        reset_request_id(token)

    exchange = rabbit.exchange
    publish: Any = exchange.publish
    publish.assert_awaited_once()
    message = publish.await_args.args[0]
    assert publish.await_args.kwargs == {"routing_key": "user.email_confirmation_requested"}
    assert json.loads(message.body) == {"email": "a@b.c", "n": "Юля"}
    assert message.content_type == "application/json"
    assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
    assert message.correlation_id == "req-42"
    assert message.message_id


async def test_publish_without_request_id(settings: Settings, connection: MagicMock) -> None:
    rabbit = Rabbit(settings)
    await rabbit.connect()

    await rabbit.publish("k", {})
    await rabbit.publish("k", {})

    publish: Any = rabbit.exchange.publish
    first, second = (call.args[0] for call in publish.await_args_list)
    assert first.correlation_id is None
    assert first.message_id != second.message_id


async def test_disconnect_closes_and_is_idempotent(
    settings: Settings, connection: MagicMock
) -> None:
    rabbit = Rabbit(settings)
    await rabbit.disconnect()  # без connect() — ничего не делает

    await rabbit.connect()
    await rabbit.disconnect()
    await rabbit.disconnect()

    connection.close.assert_awaited_once()
    with pytest.raises(RuntimeError, match="not connected"):
        _ = rabbit.exchange


async def test_live_publish_reaches_bound_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAND_API_KEY", "key")
    monkeypatch.setenv("RABBITMQ_URL", LIVE_URL)
    # Отдельный exchange на тест: не мешает стенду и другим прогонам
    monkeypatch.setenv("EVENTS_EXCHANGE", f"stand.test.{uuid.uuid4().hex[:12]}")
    rabbit = Rabbit(Settings())
    try:
        await rabbit.open()
    except (OSError, aio_pika.exceptions.AMQPError) as exc:
        pytest.skip(f"RabbitMQ is not available ({exc}); run make up")
    try:
        queue = await rabbit.channel.declare_queue(exclusive=True, auto_delete=True)
        await queue.bind(rabbit.exchange, routing_key="test.#")

        await rabbit.publish("test.event", {"hello": "мир"})

        message = await queue.get(timeout=5)
        await message.ack()
        assert json.loads(message.body) == {"hello": "мир"}
        assert message.routing_key == "test.event"
        await rabbit.exchange.delete()
    finally:
        await rabbit.disconnect()
