"""RabbitMQ: соединение aio-pika и topic exchange доменных событий как nuke-di Client."""

import asyncio
import json
import uuid
from collections.abc import Mapping
from dataclasses import field
from typing import Any

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractConnection, AbstractExchange
from nuke_di import Client, client_dataclass

from stand_core.grpc.context import request_id
from stand_core.logging import get_logger
from stand_core.settings import Settings

logger = get_logger(__name__)


@client_dataclass
class Rabbit(Client):
    """Соединение с RabbitMQ, канал и exchange событий `Settings.events_exchange`.

    Поля — только зависимости; соединение (robust: само переподключается после обрыва), канал
    с publisher confirms и durable topic exchange создаются в `open()`. Очереди объявляет
    потребитель — публикующему сервису они не нужны.

    `connect()` при старте ошибку брокера не бросает, а только логирует: издатель (users-service)
    обязан стартовать и без RabbitMQ (docs/decisions.md §28), а `publish` повторит `open()` сам.
    Потребитель, которому брокер обязателен, зовёт `open()` в своём `connect()` — и падает.
    """

    _settings: Settings
    _connection: AbstractConnection | None = field(default=None, init=False)
    _channel: AbstractChannel | None = field(default=None, init=False)
    _exchange: AbstractExchange | None = field(default=None, init=False)
    _opening: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def channel(self) -> AbstractChannel:
        if self._channel is None:
            raise RuntimeError("Rabbit is not connected")
        return self._channel

    @property
    def exchange(self) -> AbstractExchange:
        if self._exchange is None:
            raise RuntimeError("Rabbit is not connected")
        return self._exchange

    async def connect(self) -> None:
        try:
            await self.open()
        except Exception as exc:
            logger.warning("rabbit.connect_failed", error=str(exc) or type(exc).__name__)

    async def open(self) -> None:
        """Подключиться, если ещё не подключены; ошибка брокера или пустой URL — наружу."""
        async with self._opening:
            if self._exchange is None:
                await self._open()

    async def _open(self) -> None:
        url = self._settings.rabbitmq_url
        if not url:
            raise RuntimeError("RABBITMQ_URL is not set")
        connection = await aio_pika.connect_robust(
            url, timeout=self._settings.connect_timeout_seconds
        )
        try:
            # on_return_raises: событие, которое некуда положить (потребитель ещё не объявил
            # очередь), — ошибка publish, а не молча выброшенное брокером сообщение
            channel = await connection.channel(on_return_raises=True)
            exchange = await channel.declare_exchange(
                self._settings.events_exchange, aio_pika.ExchangeType.TOPIC, durable=True
            )
        except BaseException:
            await connection.close()
            raise
        self._connection, self._channel, self._exchange = connection, channel, exchange

    async def disconnect(self) -> None:
        if self._connection is not None:
            await self._connection.close()
        self._connection = self._channel = self._exchange = None

    async def publish(self, routing_key: str, payload: Mapping[str, Any]) -> None:
        """Публикует событие JSON-ом в exchange событий; ждёт подтверждения брокера.

        Не подключены (брокера не было при старте) — сначала `open()`, его ошибка — наружу.
        Сообщение persistent (переживает рестарт брокера при durable-очереди). `message_id` —
        уникален для каждого сообщения, `correlation_id` — `request_id` текущего вызова: по нему
        письмо в журнале потребителя связывается с логами исходного RPC.
        """
        message = aio_pika.Message(
            body=json.dumps(payload, ensure_ascii=False).encode(),
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=uuid.uuid4().hex,
            correlation_id=request_id(),
        )
        await self.open()
        await self.exchange.publish(message, routing_key=routing_key)
