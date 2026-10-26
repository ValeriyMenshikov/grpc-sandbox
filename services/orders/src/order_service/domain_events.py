"""Доменное событие `order.status_changed` в RabbitMQ (exchange `stand.events`).

Публикация best-effort: статус уже в Postgres, а пока ни один потребитель не объявил очередь,
`Rabbit.publish` падает (`on_return_raises=True`). Поэтому ошибка брокера только логируется.
"""

import asyncio

from nuke_di import Client, client_dataclass
from stand_core.clients import Rabbit
from stand_core.events import ORDER_STATUS_CHANGED, OrderStatusChanged, order_status_changed_payload
from stand_core.logging import get_logger

from order_service.models import OrderStatusEvent

logger = get_logger(__name__)

# Сколько ждать подтверждения брокера: robust-соединение aio-pika при обрыве ждёт
# переподключения, а не падает сразу — смену статуса это задерживать не должно
PUBLISH_TIMEOUT_S = 2.0


def order_status_changed(event: OrderStatusEvent) -> OrderStatusChanged:
    return OrderStatusChanged(
        order_id=event.order_id,
        user_id=event.user_id,
        status=event.status.value,
        changed_at=event.changed_at,
        email=event.email,
    )


@client_dataclass
class DomainEvents(Client):
    _rabbit: Rabbit

    async def publish_quietly(self, event: OrderStatusEvent) -> None:
        """Публикация без ошибки наружу; `request_id` в `correlation_id` ставит `Rabbit.publish`."""
        try:
            async with asyncio.timeout(PUBLISH_TIMEOUT_S):
                await self._rabbit.publish(
                    ORDER_STATUS_CHANGED, order_status_changed_payload(order_status_changed(event))
                )
        except Exception as exc:
            logger.warning(
                "orders.domain_publish_failed",
                order_id=event.order_id,
                status=event.status.value,
                error=str(exc) or type(exc).__name__,
            )
