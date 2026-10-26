"""Потребитель очереди писем: событие из RabbitMQ → письмо по SMTP → запись в журнал."""

from collections.abc import Awaitable, Callable
from dataclasses import field

from aio_pika.abc import AbstractIncomingMessage, AbstractQueue
from nuke_di import Client, client_dataclass
from stand_core.clients import Rabbit
from stand_core.events import (
    USER_EMAIL_CONFIRMATION_REQUESTED,
    InvalidEvent,
    parse_email_confirmation,
)
from stand_core.logging import get_logger
from structlog.typing import FilteringBoundLogger

from notification_service.mailer import Mailer
from notification_service.models import NotificationStatus
from notification_service.repository import NotificationRepository
from notification_service.settings import NotificationSettings
from notification_service.templates import EmailContent, confirmation_email

logger = get_logger(__name__)

# Сколько неподтверждённых сообщений брокер отдаёт сразу: письма шлются по одному
PREFETCH_COUNT = 10


@client_dataclass
class EmailConsumer(Client):
    """Фоновая задача внутри notification-service: читает `email_queue` и отправляет письма.

    Доставка at-least-once: `ack` — только после того, как SMTP принял письмо, поэтому падение
    сервиса между отправкой и `ack` даёт дубль письма (для кода подтверждения это допустимо).
    Ошибка отправки и неразбираемое тело — `nack(requeue=False)`: сообщение уходит в dead-letter,
    а не крутится в очереди бесконечно. Каждая попытка пишется в журнал (`ListNotifications`).
    """

    _rabbit: Rabbit
    _mailer: Mailer
    _repository: NotificationRepository
    _settings: NotificationSettings
    _queue: AbstractQueue | None = field(default=None, init=False)

    @property
    def queue(self) -> AbstractQueue:
        if self._queue is None:
            raise RuntimeError("EmailConsumer is not connected")
        return self._queue

    async def connect(self) -> None:
        self._queue = await declare_queue(
            self._rabbit,
            queue=self._settings.email_queue,
            routing_key=USER_EMAIL_CONFIRMATION_REQUESTED,
            dead_letter_exchange=self._settings.dead_letter_exchange,
            dead_letter_queue=self._settings.dead_letter_queue,
        )

    async def run(self) -> None:
        """Потребление до отмены задачи; robust-соединение само переподключается к брокеру."""
        await consume(self.queue, self.handle, "email")

    async def handle(self, message: AbstractIncomingMessage) -> None:
        """Обработать одно сообщение: ошибки отправки и разбора не бросаются, только ack/nack."""
        log = logger.bind(message_id=message.message_id, request_id=message.correlation_id)
        try:
            event = parse_email_confirmation(message.body)
        except InvalidEvent as exc:
            log.warning("notifications.invalid_event", error=str(exc))
            await record_quietly(self._repository, log, "", "", NotificationStatus.FAILED, str(exc))
            await message.nack(requeue=False)
            return

        log = log.bind(request_id=event.request_id or message.correlation_id, to_email=event.email)
        await deliver(
            self._mailer, self._repository, log, message, event.email, confirmation_email(event)
        )


async def declare_queue(
    rabbit: Rabbit,
    *,
    queue: str,
    routing_key: str,
    dead_letter_exchange: str,
    dead_letter_queue: str,
) -> AbstractQueue:
    """Очередь, привязанная к exchange событий, и её dead-letter (fanout-exchange + очередь)."""
    # Rabbit.connect() без брокера стартует молча; потребителю брокер обязателен — падаем
    await rabbit.open()
    channel = rabbit.channel
    await channel.set_qos(prefetch_count=PREFETCH_COUNT)
    # Мёртвые сообщения — в fanout-exchange и одну очередь: смотреть руками, переотправлять нечем
    dead_exchange = await channel.declare_exchange(dead_letter_exchange, "fanout", durable=True)
    dead = await channel.declare_queue(dead_letter_queue, durable=True)
    await dead.bind(dead_exchange)
    declared = await channel.declare_queue(
        queue, durable=True, arguments={"x-dead-letter-exchange": dead_letter_exchange}
    )
    await declared.bind(rabbit.exchange, routing_key=routing_key)
    return declared


async def consume(
    queue: AbstractQueue,
    handle: Callable[[AbstractIncomingMessage], Awaitable[None]],
    name: str,
) -> None:
    """Потребление до отмены задачи; `handle` сам делает ack/nack и ошибок не бросает.

    Конец итератора без отмены — ошибка: потребитель молча встал бы, а сервис остался healthy.
    """
    async with queue.iterator() as messages:
        async for message in messages:
            try:
                await handle(message)
            except Exception as exc:
                # ack/nack на оборванном канале: брокер сам вернёт сообщение в очередь
                logger.warning("notifications.ack_failed", error=str(exc))
    raise RuntimeError(f"{name} queue consumption stopped")


async def deliver(
    mailer: Mailer,
    repository: NotificationRepository,
    log: FilteringBoundLogger,
    message: AbstractIncomingMessage,
    to_email: str,
    content: EmailContent,
) -> None:
    """Письмо по SMTP: принято — запись `SENT` и `ack`; ошибка — `FAILED` и dead-letter."""
    try:
        await mailer.send(to_email, content)
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        log.error("notifications.email_failed", error=error)
        await record_quietly(
            repository, log, to_email, content.subject, NotificationStatus.FAILED, error
        )
        await message.nack(requeue=False)
        return

    log.info("notifications.email_sent", subject=content.subject)
    await record_quietly(repository, log, to_email, content.subject, NotificationStatus.SENT)
    await message.ack()


async def record_quietly(
    repository: NotificationRepository,
    log: FilteringBoundLogger,
    to_email: str,
    subject: str,
    status: NotificationStatus,
    error: str = "",
) -> None:
    """Запись в журнал; без Postgres сообщение всё равно подтверждается — журнал вторичен."""
    try:
        await repository.record(to_email, subject, status, error)
    except Exception as exc:
        log.warning("notifications.journal_failed", status=status.value, error=str(exc))
