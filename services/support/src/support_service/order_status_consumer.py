"""Потребитель `order.status_changed`: проекция смен статуса заказа `support.order_events`."""

import asyncio

import aio_pika
from aio_pika.abc import AbstractIncomingMessage, AbstractQueue
from nuke_di import Client, client_dataclass
from stand_core.clients import Rabbit
from stand_core.events import ORDER_STATUS_CHANGED, InvalidEvent, parse_order_status_changed
from stand_core.logging import get_logger

from support_service.convert import order_status_pb
from support_service.models import OrderEvent
from support_service.repository import ChatRepository
from support_service.settings import SupportSettings

logger = get_logger(__name__)

# Сколько неподтверждённых сообщений брокер отдаёт сразу
PREFETCH_COUNT = 10


@client_dataclass
class OrderStatusConsumer(Client):
    """Фоновая задача внутри support-service: читает `order_events_queue` в проекцию.

    В отличие от потребителей notification-service, брокер support-service не обязателен:
    `Chat` и `GetChatHistory` обязаны работать без RabbitMQ (ТЗ §6.5, §10). Поэтому брокер не
    открывается в `connect()`, а `run()` — внешний цикл: подключиться, объявить очередь,
    потреблять; любая ошибка — лог, пауза с экспоненциальным backoff и новая попытка. Пока
    брокера нет, проекция просто отстаёт — штатная eventual consistency.

    Доставка at-least-once: `ack` — после записи в Postgres, повтор события вставка игнорирует.
    Битое тело и неизвестный статус — `nack(requeue=False)` в dead-letter: в таблицу мусор не
    попадает и сообщение не крутится в очереди. Ошибка записи в Postgres — наружу, в цикл
    `run()`: соединение закрывается, неподтверждённые сообщения брокер вернёт в очередь,
    а повтор будет после паузы, а не горячим циклом.
    """

    _rabbit: Rabbit
    _repository: ChatRepository
    _settings: SupportSettings

    async def run(self) -> None:
        """Потребление с переподключением до отмены задачи; сам не завершается."""
        delay = self._settings.order_events_reconnect_delay_s
        while True:
            try:
                queue = await self.declare()
                # Подключились — следующая неудача снова начинается с короткой паузы
                delay = self._settings.order_events_reconnect_delay_s
                logger.info("support.order_events_consuming", queue=queue.name)
                await self.consume(queue)
            except Exception as exc:
                logger.warning(
                    "support.order_events_consumer_failed",
                    error=str(exc) or type(exc).__name__,
                    retry_in_s=delay,
                )
                await self._reset()
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._settings.order_events_reconnect_max_delay_s)

    async def declare(self) -> AbstractQueue:
        """Очередь, привязанная к exchange событий, и её dead-letter (fanout-exchange + очередь)."""
        await self._rabbit.open()
        channel = self._rabbit.channel
        await channel.set_qos(prefetch_count=PREFETCH_COUNT)
        dead_letter_exchange = self._settings.order_events_dead_letter_exchange
        dead_exchange = await channel.declare_exchange(
            dead_letter_exchange, aio_pika.ExchangeType.FANOUT, durable=True
        )
        dead = await channel.declare_queue(
            self._settings.order_events_dead_letter_queue, durable=True
        )
        await dead.bind(dead_exchange)
        queue = await channel.declare_queue(
            self._settings.order_events_queue,
            durable=True,
            arguments={"x-dead-letter-exchange": dead_letter_exchange},
        )
        await queue.bind(self._rabbit.exchange, routing_key=ORDER_STATUS_CHANGED)
        return queue

    async def consume(self, queue: AbstractQueue) -> None:
        """Потребление до обрыва; конец итератора без отмены — ошибка: `run()` переподключится."""
        async with queue.iterator() as messages:
            async for message in messages:
                await self.handle(message)
        raise RuntimeError("order events queue consumption stopped")

    async def handle(self, message: AbstractIncomingMessage) -> None:
        """Обработать одно сообщение; ошибка Postgres — наружу, сообщение остаётся без ack."""
        log = logger.bind(message_id=message.message_id, request_id=message.correlation_id)
        try:
            event = parse_order_status_changed(message.body)
            if order_status_pb(event.status) is None:
                raise InvalidEvent(f"unknown order status {event.status!r}")
        except InvalidEvent as exc:
            log.warning("support.invalid_order_event", error=str(exc))
            await message.nack(requeue=False)
            return

        await self._repository.record_order_event(
            OrderEvent(order_id=event.order_id, status=event.status, changed_at=event.changed_at)
        )
        log.info(
            "support.order_event_recorded",
            request_id=event.request_id or message.correlation_id,
            order_id=event.order_id,
            status=event.status,
        )
        await message.ack()

    async def _reset(self) -> None:
        """Закрыть соединение: следующий `open()` подключится заново, а не к сломанному каналу."""
        try:
            await self._rabbit.disconnect()
        except Exception as exc:
            logger.warning("support.order_events_disconnect_failed", error=str(exc))
