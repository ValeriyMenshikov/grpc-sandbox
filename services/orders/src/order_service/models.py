"""Доменные типы order-service: репозиторий и хэндлеры не зависят от proto."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class OrderStatus(StrEnum):
    CREATED = "CREATED"
    PAID = "PAID"
    ASSEMBLING = "ASSEMBLING"
    HANDED_TO_COURIER = "HANDED_TO_COURIER"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


# Отменить можно только до передачи курьеру
CANCELLABLE_STATUSES = frozenset({OrderStatus.CREATED, OrderStatus.PAID, OrderStatus.ASSEMBLING})


@dataclass(frozen=True)
class OrderItem:
    product_id: str
    name: str
    quantity: int
    # Цена за штуку на момент оформления
    price_kopecks: int


@dataclass(frozen=True)
class Order:
    order_id: str
    user_id: str
    status: OrderStatus
    items: tuple[OrderItem, ...]
    created_at: datetime
    updated_at: datetime

    @property
    def total_kopecks(self) -> int:
        return sum(item.price_kopecks * item.quantity for item in self.items)
