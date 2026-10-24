"""REST-эндпоинты gateway: каждый — один вызов gRPC-сервиса и перевод ответа в JSON."""

from typing import Annotated

from catalog.v1 import catalog_pb2
from common.v1 import money_pb2
from fastapi import Header, Query, status
from nuke_di.fastapi import ClientRouter
from orders.v1 import orders_pb2
from users.v1 import users_pb2

from gateway import schemas
from gateway.clients import CatalogClient, OrdersClient, UsersClient

router = ClientRouter()

ROLES: dict[schemas.Role, users_pb2.UserRole.ValueType] = {
    "BUYER": users_pb2.USER_ROLE_BUYER,
    "SELLER": users_pb2.USER_ROLE_SELLER,
}

PageSize = Annotated[int, Query(ge=0, description="0 — размер страницы по умолчанию сервиса")]
PageToken = Annotated[str, Query(description="next_page_token предыдущей страницы")]


@router.get("/healthz")
async def healthz() -> schemas.Health:
    """Healthcheck контейнера: процесс отвечает, соседей не трогает."""
    return schemas.Health()


# --- auth и профиль ---


@router.post("/auth/sign-up", status_code=status.HTTP_201_CREATED)
async def sign_up(body: schemas.SignUpIn, users: UsersClient) -> schemas.User:
    response = await users.sign_up(
        users_pb2.SignUpRequest(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            role=ROLES[body.role],
        )
    )
    return schemas.user(response.user)


@router.post("/auth/confirm")
async def confirm(body: schemas.ConfirmIn, users: UsersClient) -> schemas.User:
    response = await users.confirm_email(
        users_pb2.ConfirmEmailRequest(email=body.email, code=body.code)
    )
    return schemas.user(response.user)


@router.post("/auth/sign-in")
async def sign_in(body: schemas.SignInIn, users: UsersClient) -> schemas.SignInOut:
    response = await users.sign_in(
        users_pb2.SignInRequest(email=body.email, password=body.password)
    )
    return schemas.sign_in(response)


@router.get("/me")
async def me(users: UsersClient) -> schemas.User:
    response = await users.get_me()
    return schemas.user(response.user)


# --- каталог ---


@router.get("/products")
async def search_products(
    catalog: CatalogClient,
    query: str = "",
    category: str | None = None,
    min_price_kopecks: Annotated[int | None, Query(ge=0)] = None,
    max_price_kopecks: Annotated[int | None, Query(ge=0)] = None,
    sort: schemas.ProductSort = "name",
    page_size: PageSize = 0,
    page_token: PageToken = "",
) -> schemas.ProductsPage:
    request = catalog_pb2.SearchProductsRequest(
        query=query,
        sort=schemas.SORT_ORDER[sort],
        pagination=money_pb2.Pagination(page_size=page_size, page_token=page_token),
    )
    if category is not None:
        request.category = category
    if min_price_kopecks is not None:
        request.min_price_kopecks = min_price_kopecks
    if max_price_kopecks is not None:
        request.max_price_kopecks = max_price_kopecks
    return schemas.products_page(await catalog.search_products(request))


@router.get("/products/{product_id}")
async def get_product(product_id: str, catalog: CatalogClient) -> schemas.Product:
    response = await catalog.get_product(product_id)
    return schemas.product(response.product)


# --- корзина и заказы ---


@router.get("/cart")
async def get_cart(orders: OrdersClient) -> schemas.Cart:
    response = await orders.get_cart()
    return schemas.cart(response.cart)


@router.post("/cart/items")
async def add_cart_item(body: schemas.AddCartItemIn, orders: OrdersClient) -> schemas.Cart:
    response = await orders.add_cart_item(body.product_id, body.quantity)
    return schemas.cart(response.cart)


@router.delete("/cart/items/{product_id}")
async def remove_cart_item(product_id: str, orders: OrdersClient) -> schemas.Cart:
    response = await orders.remove_cart_item(product_id)
    return schemas.cart(response.cart)


@router.post("/checkout")
async def checkout(
    orders: OrdersClient,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> schemas.Order:
    """Заголовок `Idempotency-Key` уходит в metadata `idempotency-key` как есть."""
    response = await orders.checkout(idempotency_key)
    return schemas.order(response.order)


@router.get("/orders")
async def list_orders(
    orders: OrdersClient,
    status: schemas.OrderStatus | None = None,
    page_size: PageSize = 0,
    page_token: PageToken = "",
) -> schemas.OrdersPage:
    request = orders_pb2.ListOrdersRequest(
        pagination=money_pb2.Pagination(page_size=page_size, page_token=page_token)
    )
    if status is not None:
        request.status = orders_pb2.OrderStatus.Value(f"ORDER_STATUS_{status}")
    return schemas.orders_page(await orders.list_orders(request))


@router.get("/orders/{order_id}")
async def get_order(order_id: str, orders: OrdersClient) -> schemas.Order:
    response = await orders.get_order(order_id)
    return schemas.order(response.order)
