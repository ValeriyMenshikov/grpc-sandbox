"""Журнал писем в памяти и SMTP-заглушка для unit-тестов."""

import uuid
from datetime import UTC, datetime, timedelta

from notification_service.mailer import Mailer
from notification_service.models import Notification, NotificationStatus
from notification_service.repository import NotificationRepository
from notification_service.templates import EmailContent

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


class FakeRepository(NotificationRepository):
    def __init__(self) -> None:
        self.notifications: list[Notification] = []
        self._clock = EPOCH

    async def connect(self) -> None:
        pass

    async def record(
        self, to_email: str, subject: str, status: NotificationStatus, error: str = ""
    ) -> Notification:
        self._clock += timedelta(minutes=1)
        notification = Notification(
            str(uuid.uuid4()), to_email, subject, status, error, self._clock
        )
        self.notifications.append(notification)
        return notification

    async def list_notifications(
        self, to_email: str | None, offset: int, limit: int
    ) -> list[Notification]:
        matching = [
            notification
            for notification in reversed(self.notifications)
            if to_email is None or notification.to_email.lower() == to_email.lower()
        ]
        return matching[offset : offset + limit]


class FakeMailer(Mailer):
    """Запоминает письма вместо SMTP; `error` — что бросить вместо отправки."""

    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[tuple[str, EmailContent]] = []
        self.error = error

    async def send(self, to_email: str, content: EmailContent) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append((to_email, content))
