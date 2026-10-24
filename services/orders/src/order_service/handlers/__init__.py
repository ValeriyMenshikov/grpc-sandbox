"""Хэндлеры order-service: импорт пакета регистрирует их в `GRPC_HANDLERS`."""

from order_service.handlers import (
    add_cart_item_u_u,
    cancel_order_u_u,
    checkout_u_u,
    get_cart_u_u,
    get_order_u_u,
    list_orders_u_u,
    remove_cart_item_u_u,
    track_order_u_s,
)

__all__ = (
    "add_cart_item_u_u",
    "cancel_order_u_u",
    "checkout_u_u",
    "get_cart_u_u",
    "get_order_u_u",
    "list_orders_u_u",
    "remove_cart_item_u_u",
    "track_order_u_s",
)
