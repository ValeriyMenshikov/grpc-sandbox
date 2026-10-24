"""gRPC-клиенты gateway к user-, catalog- и order-service на базовом клиенте stand_core.

`x-api-key` gateway и `x-request-id` HTTP-запроса подставляет базовый клиент; методы от имени
пользователя идут с его `authorization` (`forward_authorization=True`) — проверяет его сам сервис.
"""

from catalog.v1 import catalog_pb2
from orders.v1 import orders_pb2
from stand_core.clients import GrpcClient
from users.v1 import users_pb2

USER_SERVICE = "/users.v1.UserService"
CATALOG_SERVICE = "/catalog.v1.CatalogService"
ORDER_SERVICE = "/orders.v1.OrderService"

IDEMPOTENCY_KEY = "idempotency-key"


class UsersClient(GrpcClient):
    address_env = "USERS_ADDR"
    dependency = "users"

    async def sign_up(self, request: users_pb2.SignUpRequest) -> users_pb2.SignUpResponse:
        return await self.unary(f"{USER_SERVICE}/SignUp", request, users_pb2.SignUpResponse)

    async def confirm_email(
        self, request: users_pb2.ConfirmEmailRequest
    ) -> users_pb2.ConfirmEmailResponse:
        return await self.unary(
            f"{USER_SERVICE}/ConfirmEmail", request, users_pb2.ConfirmEmailResponse
        )

    async def sign_in(self, request: users_pb2.SignInRequest) -> users_pb2.SignInResponse:
        return await self.unary(f"{USER_SERVICE}/SignIn", request, users_pb2.SignInResponse)

    async def get_me(self) -> users_pb2.GetMeResponse:
        return await self.unary(
            f"{USER_SERVICE}/GetMe",
            users_pb2.GetMeRequest(),
            users_pb2.GetMeResponse,
            forward_authorization=True,
        )


class CatalogClient(GrpcClient):
    address_env = "CATALOG_ADDR"
    dependency = "catalog"

    async def get_product(self, product_id: str) -> catalog_pb2.GetProductResponse:
        return await self.unary(
            f"{CATALOG_SERVICE}/GetProduct",
            catalog_pb2.GetProductRequest(product_id=product_id),
            catalog_pb2.GetProductResponse,
        )

    async def search_products(
        self, request: catalog_pb2.SearchProductsRequest
    ) -> catalog_pb2.SearchProductsResponse:
        return await self.unary(
            f"{CATALOG_SERVICE}/SearchProducts", request, catalog_pb2.SearchProductsResponse
        )


class OrdersClient(GrpcClient):
    """Все методы order-service — Auth: user, поэтому каждый вызов несёт `authorization`."""

    address_env = "ORDERS_ADDR"
    dependency = "orders"

    async def get_cart(self) -> orders_pb2.GetCartResponse:
        return await self.unary(
            f"{ORDER_SERVICE}/GetCart",
            orders_pb2.GetCartRequest(),
            orders_pb2.GetCartResponse,
            forward_authorization=True,
        )

    async def add_cart_item(self, product_id: str, quantity: int) -> orders_pb2.AddCartItemResponse:
        return await self.unary(
            f"{ORDER_SERVICE}/AddCartItem",
            orders_pb2.AddCartItemRequest(product_id=product_id, quantity=quantity),
            orders_pb2.AddCartItemResponse,
            forward_authorization=True,
        )

    async def remove_cart_item(self, product_id: str) -> orders_pb2.RemoveCartItemResponse:
        return await self.unary(
            f"{ORDER_SERVICE}/RemoveCartItem",
            orders_pb2.RemoveCartItemRequest(product_id=product_id),
            orders_pb2.RemoveCartItemResponse,
            forward_authorization=True,
        )

    async def checkout(self, idempotency_key: str | None) -> orders_pb2.CheckoutResponse:
        # Без ключа вызов всё равно уходит: проверку (и INVALID_ARGUMENT) делает order-service
        metadata = () if idempotency_key is None else ((IDEMPOTENCY_KEY, idempotency_key),)
        return await self.unary(
            f"{ORDER_SERVICE}/Checkout",
            orders_pb2.CheckoutRequest(),
            orders_pb2.CheckoutResponse,
            forward_authorization=True,
            metadata=metadata,
        )

    async def get_order(self, order_id: str) -> orders_pb2.GetOrderResponse:
        return await self.unary(
            f"{ORDER_SERVICE}/GetOrder",
            orders_pb2.GetOrderRequest(order_id=order_id),
            orders_pb2.GetOrderResponse,
            forward_authorization=True,
        )

    async def list_orders(
        self, request: orders_pb2.ListOrdersRequest
    ) -> orders_pb2.ListOrdersResponse:
        return await self.unary(
            f"{ORDER_SERVICE}/ListOrders",
            request,
            orders_pb2.ListOrdersResponse,
            forward_authorization=True,
        )
