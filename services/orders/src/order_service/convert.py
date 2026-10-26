"""Доменный Order и корзина ↔ сообщения orders.v1, копейки → Money."""

from datetime import datetime

from common.v1 import money_pb2
from google.protobuf.timestamp_pb2 import Timestamp
from orders.v1 import orders_pb2

from order_service.models import Order, OrderStatus, StatusChange

CURRENCY = "RUB"
NANOS_PER_KOPECK = 10_000_000
KOPECKS_PER_UNIT = 100

STATUS_TO_PROTO: dict[OrderStatus, orders_pb2.OrderStatus.ValueType] = {
    OrderStatus.CREATED: orders_pb2.ORDER_STATUS_CREATED,
    OrderStatus.PAID: orders_pb2.ORDER_STATUS_PAID,
    OrderStatus.ASSEMBLING: orders_pb2.ORDER_STATUS_ASSEMBLING,
    OrderStatus.HANDED_TO_COURIER: orders_pb2.ORDER_STATUS_HANDED_TO_COURIER,
    OrderStatus.DELIVERED: orders_pb2.ORDER_STATUS_DELIVERED,
    OrderStatus.CANCELLED: orders_pb2.ORDER_STATUS_CANCELLED,
}
STATUS_FROM_PROTO = {proto: status for status, proto in STATUS_TO_PROTO.items()}


def timestamp(value: datetime) -> Timestamp:
    result = Timestamp()
    result.FromDatetime(value)
    return result


def money(kopecks: int) -> money_pb2.Money:
    units, rest = divmod(kopecks, KOPECKS_PER_UNIT)
    return money_pb2.Money(currency_code=CURRENCY, units=units, nanos=rest * NANOS_PER_KOPECK)


def order_pb(order: Order) -> orders_pb2.Order:
    return orders_pb2.Order(
        order_id=order.order_id,
        user_id=order.user_id,
        status=STATUS_TO_PROTO[order.status],
        items=[
            orders_pb2.OrderItem(
                product_id=item.product_id,
                name=item.name,
                quantity=item.quantity,
                unit_price=money(item.price_kopecks),
            )
            for item in order.items
        ],
        total=money(order.total_kopecks),
        created_at=timestamp(order.created_at),
        updated_at=timestamp(order.updated_at),
    )


def status_change_pb(change: StatusChange) -> orders_pb2.OrderStatusChange:
    return orders_pb2.OrderStatusChange(
        status=STATUS_TO_PROTO[change.status], changed_at=timestamp(change.changed_at)
    )
