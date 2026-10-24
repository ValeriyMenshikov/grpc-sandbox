"""Бот чата: отвечает на вопросы о статусе заказа статусом из order-service."""

from orders.v1 import orders_pb2

# Слова, на которые отвечает бот (без учёта регистра, подстрокой)
TRIGGERS = ("статус", "где")

GREETING = "Здравствуйте, я оператор поддержки. Чем могу помочь?"
STATUS_UNAVAILABLE = "Не удалось получить статус, попробуйте позже"

STATUS_TEXT: dict[orders_pb2.OrderStatus.ValueType, str] = {
    orders_pb2.ORDER_STATUS_CREATED: "создан",
    orders_pb2.ORDER_STATUS_PAID: "оплачен",
    orders_pb2.ORDER_STATUS_ASSEMBLING: "собирается на складе",
    orders_pb2.ORDER_STATUS_HANDED_TO_COURIER: "передан курьеру",
    orders_pb2.ORDER_STATUS_DELIVERED: "доставлен",
    orders_pb2.ORDER_STATUS_CANCELLED: "отменён",
}


def is_status_question(text: str) -> bool:
    lowered = text.lower()
    return any(trigger in lowered for trigger in TRIGGERS)


def status_reply(order: orders_pb2.Order) -> str:
    status = STATUS_TEXT.get(order.status)
    if status is None:
        return STATUS_UNAVAILABLE
    return f"Заказ {order.order_id}: {status}"
