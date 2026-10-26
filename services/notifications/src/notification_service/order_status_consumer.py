"""Потребитель `order.status_changed`: письмо покупателю, когда заказ доставлен."""

from dataclasses import field

from aio_pika.abc import AbstractIncomingMessage, AbstractQueue
from nuke_di import Client, client_dataclass
from stand_core.clients import Rabbit
from stand_core.events import ORDER_STATUS_CHANGED, InvalidEvent, parse_order_status_changed
from stand_core.logging import get_logger

from notification_service.consumer import consume, declare_queue, deliver, record_quietly
from notification_service.mailer import Mailer
from notification_service.models import NotificationStatus
from notification_service.repository import NotificationRepository
from notification_service.settings import NotificationSettings
from notification_service.templates import delivered_email

logger = get_logger(__name__)

# Статусы заказа, которые знает этот потребитель (orders.v1 OrderStatus). Другое значение —
# издатель новее потребителя: событие не угадываем, а отправляем в dead-letter
KNOWN_STATUSES = frozenset(
    {"CREATED", "PAID", "ASSEMBLING", "HANDED_TO_COURIER", "DELIVERED", "CANCELLED"}
)
DELIVERED = "DELIVERED"

SKIPPED_NO_EMAIL = "order has no buyer email"


@client_dataclass
class OrderStatusConsumer(Client):
    """Фоновая задача внутри notification-service: читает `order_status_queue`.

    Routing key плоский — в очередь приходит каждая смена статуса; письмо шлётся только на
    `DELIVERED`, остальные статусы подтверждаются без письма и без записи в журнал. `DELIVERED`
    без email (покупателя не удалось узнать при оформлении) — `ack` и запись `SKIPPED`: это не
    сбой, но след в журнале остаётся. Битое тело и неизвестный статус — `FAILED` и dead-letter.
    Механика доставки — как у `EmailConsumer`: `ack` только после того, как SMTP принял письмо.
    """

    _rabbit: Rabbit
    _mailer: Mailer
    _repository: NotificationRepository
    _settings: NotificationSettings
    _queue: AbstractQueue | None = field(default=None, init=False)

    @property
    def queue(self) -> AbstractQueue:
        if self._queue is None:
            raise RuntimeError("OrderStatusConsumer is not connected")
        return self._queue

    async def connect(self) -> None:
        self._queue = await declare_queue(
            self._rabbit,
            queue=self._settings.order_status_queue,
            routing_key=ORDER_STATUS_CHANGED,
            dead_letter_exchange=self._settings.order_status_dead_letter_exchange,
            dead_letter_queue=self._settings.order_status_dead_letter_queue,
        )

    async def run(self) -> None:
        """Потребление до отмены задачи; robust-соединение само переподключается к брокеру."""
        await consume(self.queue, self.handle, "order status")

    async def handle(self, message: AbstractIncomingMessage) -> None:
        """Обработать одно сообщение: ошибки отправки и разбора не бросаются, только ack/nack."""
        log = logger.bind(message_id=message.message_id, request_id=message.correlation_id)
        try:
            event = parse_order_status_changed(message.body)
            if event.status not in KNOWN_STATUSES:
                raise InvalidEvent(f"unknown order status {event.status!r}")
        except InvalidEvent as exc:
            log.warning("notifications.invalid_event", error=str(exc))
            await record_quietly(self._repository, log, "", "", NotificationStatus.FAILED, str(exc))
            await message.nack(requeue=False)
            return

        if event.status != DELIVERED:
            await message.ack()
            return

        log = log.bind(
            request_id=event.request_id or message.correlation_id,
            order_id=event.order_id,
            to_email=event.email,
        )
        content = delivered_email(event)
        if not event.email:
            log.info("notifications.email_skipped", reason=SKIPPED_NO_EMAIL)
            await record_quietly(
                self._repository,
                log,
                "",
                content.subject,
                NotificationStatus.SKIPPED,
                SKIPPED_NO_EMAIL,
            )
            await message.ack()
            return

        await deliver(self._mailer, self._repository, log, message, event.email, content)
