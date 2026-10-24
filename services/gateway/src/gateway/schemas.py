"""JSON-модели gateway и перевод из protobuf.

Ответы — собственные модели, а не `MessageToDict`: так int64 остаются числами, enum — короткими
именами (`BUYER`, `CREATED`), а цена товара — `Money`, как в корзине и заказах.
"""

from datetime import UTC, datetime
from typing import Literal

from catalog.v1 import catalog_pb2
from common.v1 import money_pb2
from google.protobuf.timestamp_pb2 import Timestamp
from orders.v1 import orders_pb2
from pydantic import BaseModel
from users.v1 import users_pb2

CURRENCY = "RUB"
KOPECKS_PER_UNIT = 100
NANOS_PER_KOPECK = 10_000_000

Role = Literal["BUYER", "SELLER"]
OrderStatus = Literal[
    "CREATED", "PAID", "ASSEMBLING", "HANDED_TO_COURIER", "DELIVERED", "CANCELLED"
]
ProductSort = Literal["name", "price_asc", "price_desc", "newest"]

SORT_ORDER: dict[ProductSort, catalog_pb2.SortOrder.ValueType] = {
    "name": catalog_pb2.SORT_ORDER_UNSPECIFIED,
    "price_asc": catalog_pb2.SORT_ORDER_PRICE_ASC,
    "price_desc": catalog_pb2.SORT_ORDER_PRICE_DESC,
    "newest": catalog_pb2.SORT_ORDER_NEWEST,
}


# --- Запросы ---


class SignUpIn(BaseModel):
    email: str
    password: str
    display_name: str = ""
    role: Role = "BUYER"


class ConfirmIn(BaseModel):
    email: str
    code: str


class SignInIn(BaseModel):
    email: str
    password: str


class AddCartItemIn(BaseModel):
    product_id: str
    quantity: int = 1


# --- Ответы ---


class Money(BaseModel):
    currency_code: str
    units: int
    nanos: int


class User(BaseModel):
    user_id: str
    email: str
    display_name: str
    phone: str | None
    role: str
    status: str
    created_at: datetime | None
    updated_at: datetime | None


class SignInOut(BaseModel):
    access_token: str
    expires_at: datetime | None
    user: User


class Product(BaseModel):
    product_id: str
    seller_id: str
    offer_id: str
    name: str
    category: str
    price: Money
    stock: int
    created_at: datetime | None
    updated_at: datetime | None


class ProductsPage(BaseModel):
    products: list[Product]
    next_page_token: str


class CartItem(BaseModel):
    product_id: str
    name: str
    quantity: int
    unit_price: Money
    available: int


class Cart(BaseModel):
    items: list[CartItem]
    total: Money


class OrderItem(BaseModel):
    product_id: str
    name: str
    quantity: int
    unit_price: Money


class Order(BaseModel):
    order_id: str
    user_id: str
    status: str
    items: list[OrderItem]
    total: Money
    created_at: datetime | None
    updated_at: datetime | None


class OrdersPage(BaseModel):
    orders: list[Order]
    next_page_token: str


class Health(BaseModel):
    status: Literal["ok"] = "ok"


# --- protobuf → модели ---


def timestamp(value: Timestamp, present: bool) -> datetime | None:
    """Время в UTC; `present=False` — поле не задано (а не 1970-01-01)."""
    return value.ToDatetime(tzinfo=UTC) if present else None


def money(value: money_pb2.Money) -> Money:
    return Money(currency_code=value.currency_code, units=value.units, nanos=value.nanos)


def kopecks_money(kopecks: int) -> Money:
    units, rest = divmod(kopecks, KOPECKS_PER_UNIT)
    return Money(currency_code=CURRENCY, units=units, nanos=rest * NANOS_PER_KOPECK)


def user(value: users_pb2.User) -> User:
    return User(
        user_id=value.user_id,
        email=value.email,
        display_name=value.display_name,
        phone=value.phone if value.HasField("phone") else None,
        role=users_pb2.UserRole.Name(value.role).removeprefix("USER_ROLE_"),
        status=users_pb2.UserStatus.Name(value.status).removeprefix("USER_STATUS_"),
        created_at=timestamp(value.created_at, value.HasField("created_at")),
        updated_at=timestamp(value.updated_at, value.HasField("updated_at")),
    )


def sign_in(value: users_pb2.SignInResponse) -> SignInOut:
    return SignInOut(
        access_token=value.access_token,
        expires_at=timestamp(value.expires_at, value.HasField("expires_at")),
        user=user(value.user),
    )


def product(value: catalog_pb2.Product) -> Product:
    return Product(
        product_id=value.product_id,
        seller_id=value.seller_id,
        offer_id=value.offer_id,
        name=value.name,
        category=value.category,
        price=kopecks_money(value.price_kopecks),
        stock=value.stock,
        created_at=timestamp(value.created_at, value.HasField("created_at")),
        updated_at=timestamp(value.updated_at, value.HasField("updated_at")),
    )


def products_page(value: catalog_pb2.SearchProductsResponse) -> ProductsPage:
    return ProductsPage(
        products=[product(each) for each in value.products],
        next_page_token=value.next_page_token,
    )


def cart(value: orders_pb2.Cart) -> Cart:
    return Cart(
        items=[
            CartItem(
                product_id=item.product_id,
                name=item.name,
                quantity=item.quantity,
                unit_price=money(item.unit_price),
                available=item.available,
            )
            for item in value.items
        ],
        total=money(value.total),
    )


def order_status(value: orders_pb2.OrderStatus.ValueType) -> str:
    return orders_pb2.OrderStatus.Name(value).removeprefix("ORDER_STATUS_")


def order(value: orders_pb2.Order) -> Order:
    return Order(
        order_id=value.order_id,
        user_id=value.user_id,
        status=order_status(value.status),
        items=[
            OrderItem(
                product_id=item.product_id,
                name=item.name,
                quantity=item.quantity,
                unit_price=money(item.unit_price),
            )
            for item in value.items
        ],
        total=money(value.total),
        created_at=timestamp(value.created_at, value.HasField("created_at")),
        updated_at=timestamp(value.updated_at, value.HasField("updated_at")),
    )


def orders_page(value: orders_pb2.ListOrdersResponse) -> OrdersPage:
    return OrdersPage(
        orders=[order(each) for each in value.orders], next_page_token=value.next_page_token
    )
