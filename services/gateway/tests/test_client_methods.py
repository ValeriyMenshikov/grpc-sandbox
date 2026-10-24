"""Методы клиентов gateway: путь и тип ответа сверяются с proto, `authorization` — с политикой.

Сеть не нужна: `unary` базового клиента подменяется записью вызова.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from catalog.v1 import catalog_pb2
from gateway.clients import CatalogClient, OrdersClient, UsersClient
from google.protobuf import symbol_database
from google.protobuf.message import Message
from orders.v1 import orders_pb2
from stand_core.clients import GrpcClient
from stand_core.settings import Settings
from users.v1 import users_pb2


class Recorded(Exception):
    def __init__(self, method: str, request: Message, response_type: type, forward: bool) -> None:
        self.method = method
        self.request = request
        self.response_type = response_type
        self.forward = forward


async def record(
    self: GrpcClient,
    method: str,
    request: Message,
    response_type: type,
    *,
    forward_authorization: bool = False,
    **_: Any,
) -> Any:
    raise Recorded(method, request, response_type, forward_authorization)


Call = Callable[[Any], Awaitable[Any]]

# (клиент, вызов, ожидаемый метод, нужен ли authorization пользователя)
CASES: list[tuple[type[GrpcClient], Call, str, bool]] = [
    (UsersClient, lambda c: c.sign_up(users_pb2.SignUpRequest()), "UserService/SignUp", False),
    (
        UsersClient,
        lambda c: c.confirm_email(users_pb2.ConfirmEmailRequest()),
        "UserService/ConfirmEmail",
        False,
    ),
    (UsersClient, lambda c: c.sign_in(users_pb2.SignInRequest()), "UserService/SignIn", False),
    (UsersClient, lambda c: c.get_me(), "UserService/GetMe", True),
    (CatalogClient, lambda c: c.get_product("p-1"), "CatalogService/GetProduct", False),
    (
        CatalogClient,
        lambda c: c.search_products(catalog_pb2.SearchProductsRequest()),
        "CatalogService/SearchProducts",
        False,
    ),
    (OrdersClient, lambda c: c.get_cart(), "OrderService/GetCart", True),
    (OrdersClient, lambda c: c.add_cart_item("p-1", 1), "OrderService/AddCartItem", True),
    (OrdersClient, lambda c: c.remove_cart_item("p-1"), "OrderService/RemoveCartItem", True),
    (OrdersClient, lambda c: c.checkout("key-1"), "OrderService/Checkout", True),
    (OrdersClient, lambda c: c.get_order("o-1"), "OrderService/GetOrder", True),
    (
        OrdersClient,
        lambda c: c.list_orders(orders_pb2.ListOrdersRequest()),
        "OrderService/ListOrders",
        True,
    ),
]

FILES = {
    UsersClient: users_pb2.DESCRIPTOR,
    CatalogClient: catalog_pb2.DESCRIPTOR,
    OrdersClient: orders_pb2.DESCRIPTOR,
}


@pytest.mark.parametrize(("client_type", "invoke", "method", "forward"), CASES)
async def test_client_method_matches_proto(
    monkeypatch: pytest.MonkeyPatch,
    client_type: type[GrpcClient],
    invoke: Call,
    method: str,
    forward: bool,
) -> None:
    monkeypatch.setattr(GrpcClient, "unary", record)
    file = FILES[client_type]
    service_name, method_name = method.split("/")
    descriptor = file.services_by_name[service_name].methods_by_name[method_name]

    with pytest.raises(Recorded) as info:
        await invoke(client_type(Settings()))

    sent = info.value
    assert sent.method == f"/{descriptor.containing_service.full_name}/{method_name}"
    assert sent.request.DESCRIPTOR is descriptor.input_type
    database = symbol_database.Default()
    assert sent.response_type is database.GetSymbol(descriptor.output_type.full_name)
    assert sent.forward is forward
