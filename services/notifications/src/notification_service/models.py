"""Доменные типы notification-service: репозиторий и хэндлеры не зависят от proto."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class NotificationStatus(StrEnum):
    # SMTP-сервер принял письмо
    SENT = "SENT"
    # Отправка не удалась или событие не разобрано; сообщение ушло в dead-letter
    FAILED = "FAILED"


@dataclass(frozen=True)
class Notification:
    """Попытка отправки письма — запись журнала."""

    notification_id: str
    # Пусто, если событие не удалось разобрать и адресат неизвестен
    to_email: str
    subject: str
    status: NotificationStatus
    # Текст ошибки для FAILED, иначе пусто
    error: str
    created_at: datetime
