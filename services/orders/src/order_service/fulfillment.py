"""Имитация доставки: CREATED → PAID → ASSEMBLING → HANDED_TO_COURIER → DELIVERED."""

import asyncio
from datetime import timedelta

from nuke_di import Client, client_dataclass
from stand_core.logging import get_logger

from order_service.events import OrderEvents
from order_service.models import OrderStatusEvent
from order_service.repository import OrderRepository
from order_service.settings import OrderSettings

logger = get_logger(__name__)

# Как часто искать заказы, которым пора на следующий шаг: не реже шага и не реже раза в 0.5 с
MAX_POLL_INTERVAL_S = 0.5


@client_dataclass
class Fulfillment(Client):
    """Фоновая задача внутри order-service: раз в шаг двигает каждый заказ на статус вперёд.

    Состояние — только в Postgres (статус и updated_at), поэтому рестарт сервиса продолжает
    доставку с того же места. Каждая смена пишется в Postgres и публикуется в Redis.
    """

    _repository: OrderRepository
    _events: OrderEvents
    _settings: OrderSettings

    @property
    def step(self) -> timedelta:
        return timedelta(milliseconds=self._settings.fulfillment_step_ms)

    @property
    def poll_interval_s(self) -> float:
        return min(self.step.total_seconds(), MAX_POLL_INTERVAL_S)

    async def advance(self) -> list[OrderStatusEvent]:
        """Один проход: продвинуть заказы, которым пора, и опубликовать смены статуса."""
        events = await self._repository.advance_due(self.step)
        for event in events:
            logger.info("orders.status_changed", order_id=event.order_id, status=event.status.value)
            await self._events.publish_quietly(event.change())
        return events

    async def run(self) -> None:
        """Проходы до отмены задачи; ошибка прохода (нет Postgres) не останавливает доставку."""
        while True:
            try:
                await self.advance()
            except Exception as exc:
                logger.warning("orders.fulfillment_failed", error=str(exc))
            await asyncio.sleep(self.poll_interval_s)
