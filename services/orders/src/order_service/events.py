"""Смены статусов заказов через Redis pub/sub: канал `orders.status.{order_id}`, JSON."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from nuke_di import Client, client_dataclass
from redis.asyncio.client import PubSub
from stand_core.clients import Redis
from stand_core.logging import get_logger

from order_service.models import OrderStatus, StatusChange
from order_service.settings import OrderSettings

logger = get_logger(__name__)

CHANNEL_PREFIX = "orders.status."


def channel(order_id: str) -> str:
    return f"{CHANNEL_PREFIX}{order_id}"


def encode(change: StatusChange) -> str:
    return json.dumps(
        {
            "order_id": change.order_id,
            "status": change.status.value,
            "changed_at": change.changed_at.isoformat(),
        }
    )


def decode(data: str) -> StatusChange:
    raw = json.loads(data)
    return StatusChange(
        raw["order_id"], OrderStatus(raw["status"]), datetime.fromisoformat(raw["changed_at"])
    )


class Subscription:
    """Подписка на смены статуса одного заказа."""

    def __init__(self, pubsub: PubSub) -> None:
        self._pubsub = pubsub

    async def next(self, wait_s: float) -> StatusChange | None:
        """Следующая смена статуса; None — за `wait_s` секунд ничего не пришло."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_s
        while (left := deadline - loop.time()) > 0:
            message: dict[str, Any] | None = await self._pubsub.get_message(
                ignore_subscribe_messages=True, timeout=left
            )
            if message is not None and message["type"] == "message":
                return decode(message["data"])
        return None


@client_dataclass
class OrderEvents(Client):
    _redis: Redis
    _settings: OrderSettings

    async def publish(self, change: StatusChange) -> None:
        await self._redis.client.publish(channel(change.order_id), encode(change))

    async def publish_quietly(self, change: StatusChange) -> None:
        """Публикация без ошибки: статус уже в Postgres, TrackOrder перечитывает его сам."""
        try:
            await self.publish(change)
        except Exception as exc:
            logger.warning("orders.publish_failed", order_id=change.order_id, error=str(exc))

    @asynccontextmanager
    async def subscribe(self, order_id: str) -> AsyncIterator[Subscription]:
        """Подписка, которая уже действует на сервере Redis: дождались подтверждения SUBSCRIBE.

        Поэтому смена статуса, опубликованная после входа в контекст, не потеряется.
        """
        # Выход из контекста PubSub — aclose(): соединение возвращается в пул
        async with self._redis.client.pubsub() as pubsub:
            await pubsub.subscribe(channel(order_id))
            async with asyncio.timeout(self._settings.connect_timeout_seconds):
                while True:
                    message = await pubsub.get_message(timeout=None)
                    if message is not None and message["type"] == "subscribe":
                        break
            yield Subscription(pubsub)
