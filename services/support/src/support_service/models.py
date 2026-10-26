"""Доменные типы support-service: репозиторий и чат не зависят от proto."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Author(StrEnum):
    CUSTOMER = "CUSTOMER"
    AGENT = "AGENT"
    BOT = "BOT"


@dataclass(frozen=True)
class Chat:
    """Чат по заказу: один на заказ, принадлежит владельцу заказа."""

    chat_id: str
    order_id: str
    user_id: str


@dataclass(frozen=True)
class ChatMessage:
    message_id: str
    chat_id: str
    author: Author
    text: str
    created_at: datetime


@dataclass(frozen=True)
class OrderEvent:
    """Смена статуса заказа из события `order.status_changed` — строка проекции.

    `status` — строка из события (значение `support.v1.OrderStatus` без префикса), проверяется
    консьюмером до записи.
    """

    order_id: str
    status: str
    changed_at: datetime
