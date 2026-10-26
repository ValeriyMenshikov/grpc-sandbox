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

# Имитация доставки: следующий статус; DELIVERED и CANCELLED — финальные
NEXT_STATUS: dict[OrderStatus, OrderStatus] = {
    OrderStatus.CREATED: OrderStatus.PAID,
    OrderStatus.PAID: OrderStatus.ASSEMBLING,
    OrderStatus.ASSEMBLING: OrderStatus.HANDED_TO_COURIER,
    OrderStatus.HANDED_TO_COURIER: OrderStatus.DELIVERED,
}
FINAL_STATUSES = frozenset({OrderStatus.DELIVERED, OrderStatus.CANCELLED})


def _delivery_steps() -> tuple[OrderStatus, ...]:
    steps = [OrderStatus.CREATED]
    while (following := NEXT_STATUS.get(steps[-1])) is not None:
        steps.append(following)
    return tuple(steps)


# Порядок шагов доставки от CREATED до DELIVERED — выводится из NEXT_STATUS; CANCELLED в него
# не входит
DELIVERY_STEPS = _delivery_steps()


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
    # Снимок email покупателя на момент оформления (для писем о заказе); "" — неизвестен
    email: str

    @property
    def total_kopecks(self) -> int:
        return sum(item.price_kopecks * item.quantity for item in self.items)


@dataclass(frozen=True)
class StatusChange:
    """Смена статуса заказа: её публикует Redis pub/sub `orders.status.{order_id}`."""

    order_id: str
    status: OrderStatus
    changed_at: datetime


@dataclass(frozen=True)
class OrderStatusEvent:
    """Смена статуса с тем, кому принадлежит заказ: из неё строится доменное событие."""

    order_id: str
    user_id: str
    # Снимок email покупателя на момент оформления; "" — неизвестен
    email: str
    status: OrderStatus
    changed_at: datetime

    def change(self) -> StatusChange:
        """Та же смена для Redis pub/sub `orders.status.{order_id}`."""
        return StatusChange(self.order_id, self.status, self.changed_at)
