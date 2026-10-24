"""Поддельные gRPC-клиенты gateway: запоминают вызовы и контекст, отвечают заготовками.

Подклассы настоящих клиентов, чтобы подменять их через `Dependencies.override`; `connect()`
ничего не открывает. `error` — исключение, которым ответит следующий вызов.
"""

from dataclasses import dataclass
from typing import Any

import grpc
from catalog.v1 import catalog_pb2
from common.v1 import money_pb2
from gateway.clients import CatalogClient, OrdersClient, UsersClient
from google.protobuf.timestamp_pb2 import Timestamp
from grpc.aio import Metadata
from orders.v1 import orders_pb2
from stand_core import Settings
from stand_core.grpc import StandError
from stand_core.grpc.context import authorization, request_id
from stand_core.grpc.errors import build_status
from users.v1 import users_pb2

CREATED_AT = Timestamp(seconds=1_767_225_600)  # 2026-01-01T00:00:00Z


@dataclass(frozen=True)
class Call:
    method: str
    args: tuple[Any, ...]
    authorization: str | None
    request_id: str | None


def rpc_error(exc: StandError) -> grpc.aio.AioRpcError:
    """Ошибка ответа сервиса, как её видит клиент: код, сообщение и rich details в trailers."""
    status = build_status(exc)
    return grpc.aio.AioRpcError(
        status.code, Metadata(), Metadata(*status.trailing_metadata), details=status.details
    )


class Recorder:
    """Вызовы клиента и ошибка, которой ответит следующий вызов."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.error: BaseException | None = None

    def __call__(self, method: str, *args: Any) -> None:
        self.calls.append(Call(method, args, authorization(), request_id()))
        if self.error is not None:
            raise self.error

    @property
    def last(self) -> Call:
        return self.calls[-1]


def user(role: users_pb2.UserRole.ValueType = users_pb2.USER_ROLE_BUYER) -> users_pb2.User:
    return users_pb2.User(
        user_id="u-1",
        email="buyer@example.com",
        display_name="Buyer",
        role=role,
        status=users_pb2.USER_STATUS_ACTIVE,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )


def rub(units: int, nanos: int = 0) -> money_pb2.Money:
    return money_pb2.Money(currency_code="RUB", units=units, nanos=nanos)


def product(product_id: str = "p-1") -> catalog_pb2.Product:
    return catalog_pb2.Product(
        product_id=product_id,
        seller_id="s-1",
        offer_id=f"offer-{product_id}",
        name="Чайник",
        category="kitchen",
        price_kopecks=199_90,
        stock=5,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )


def cart() -> orders_pb2.Cart:
    return orders_pb2.Cart(
        items=[
            orders_pb2.CartItem(
                product_id="p-1",
                name="Чайник",
                quantity=2,
                unit_price=rub(199, 900_000_000),
                available=5,
            )
        ],
        total=rub(399, 800_000_000),
    )


def order(order_id: str = "o-1") -> orders_pb2.Order:
    return orders_pb2.Order(
        order_id=order_id,
        user_id="u-1",
        status=orders_pb2.ORDER_STATUS_CREATED,
        items=[
            orders_pb2.OrderItem(
                product_id="p-1", name="Чайник", quantity=2, unit_price=rub(199, 900_000_000)
            )
        ],
        total=rub(399, 800_000_000),
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )


class FakeUsers(UsersClient):
    def __init__(self) -> None:
        super().__init__(Settings())
        self.record = Recorder()

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def sign_up(self, request: users_pb2.SignUpRequest) -> users_pb2.SignUpResponse:
        self.record("SignUp", request)
        created = user(request.role)
        created.status = users_pb2.USER_STATUS_PENDING
        return users_pb2.SignUpResponse(user=created)

    async def confirm_email(
        self, request: users_pb2.ConfirmEmailRequest
    ) -> users_pb2.ConfirmEmailResponse:
        self.record("ConfirmEmail", request)
        return users_pb2.ConfirmEmailResponse(user=user())

    async def sign_in(self, request: users_pb2.SignInRequest) -> users_pb2.SignInResponse:
        self.record("SignIn", request)
        return users_pb2.SignInResponse(
            access_token="token-1", expires_at=Timestamp(seconds=1_767_229_200), user=user()
        )

    async def get_me(self) -> users_pb2.GetMeResponse:
        self.record("GetMe")
        return users_pb2.GetMeResponse(user=user())


class FakeCatalog(CatalogClient):
    def __init__(self) -> None:
        super().__init__(Settings())
        self.record = Recorder()

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def get_product(self, product_id: str) -> catalog_pb2.GetProductResponse:
        self.record("GetProduct", product_id)
        return catalog_pb2.GetProductResponse(product=product(product_id))

    async def search_products(
        self, request: catalog_pb2.SearchProductsRequest
    ) -> catalog_pb2.SearchProductsResponse:
        self.record("SearchProducts", request)
        return catalog_pb2.SearchProductsResponse(products=[product()], next_page_token="t-2")


class FakeOrders(OrdersClient):
    def __init__(self) -> None:
        super().__init__(Settings())
        self.record = Recorder()

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def get_cart(self) -> orders_pb2.GetCartResponse:
        self.record("GetCart")
        return orders_pb2.GetCartResponse(cart=cart())

    async def add_cart_item(self, product_id: str, quantity: int) -> orders_pb2.AddCartItemResponse:
        self.record("AddCartItem", product_id, quantity)
        return orders_pb2.AddCartItemResponse(cart=cart())

    async def remove_cart_item(self, product_id: str) -> orders_pb2.RemoveCartItemResponse:
        self.record("RemoveCartItem", product_id)
        return orders_pb2.RemoveCartItemResponse(cart=orders_pb2.Cart(total=rub(0)))

    async def checkout(self, idempotency_key: str | None) -> orders_pb2.CheckoutResponse:
        self.record("Checkout", idempotency_key)
        return orders_pb2.CheckoutResponse(order=order())

    async def get_order(self, order_id: str) -> orders_pb2.GetOrderResponse:
        self.record("GetOrder", order_id)
        return orders_pb2.GetOrderResponse(order=order(order_id))

    async def list_orders(
        self, request: orders_pb2.ListOrdersRequest
    ) -> orders_pb2.ListOrdersResponse:
        self.record("ListOrders", request)
        return orders_pb2.ListOrdersResponse(orders=[order("o-2"), order("o-1")])
