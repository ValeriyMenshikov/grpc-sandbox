"""Политики авторизации методов order-service (ТЗ 6.0, 6.4): все методы — от имени покупателя."""

from stand_core.grpc import AuthPolicy

ORDER_SERVICE = "/orders.v1.OrderService"

AUTH_POLICIES: dict[str, AuthPolicy] = {
    f"{ORDER_SERVICE}/{method}": AuthPolicy.USER
    for method in (
        "AddCartItem",
        "RemoveCartItem",
        "GetCart",
        "Checkout",
        "GetOrder",
        "ListOrders",
        "CancelOrder",
    )
}
