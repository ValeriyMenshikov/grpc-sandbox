"""Smoke-сценарий против поднятого стенда (`make up`, затем `make smoke`).

Ходит в сервисы с хоста по портам из .env.example; адреса и ключ можно переопределить
переменными окружения. Код подтверждения email читается прямо из Redis.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Sequence

import grpc
import httpx
import pytest
import redis.asyncio as redis_asyncio
from catalog.v1 import catalog_pb2, catalog_pb2_grpc
from google.protobuf.timestamp_pb2 import Timestamp
from grpc_reflection.v1alpha.proto_reflection_descriptor_database import (
    ProtoReflectionDescriptorDatabase,
)
from orders.v1 import orders_pb2, orders_pb2_grpc
from support.v1 import support_pb2, support_pb2_grpc
from users.v1 import users_pb2, users_pb2_grpc

pytestmark = pytest.mark.stand

HOST = os.environ.get("STAND_HOST", "localhost")
API_KEY = os.environ.get("STAND_API_KEY", "stand-secret-key")
USERS_ADDR = f"{HOST}:{os.environ.get('USERS_PORT', '50051')}"
CATALOG_ADDR = f"{HOST}:{os.environ.get('CATALOG_PORT', '50052')}"
ORDERS_ADDR = f"{HOST}:{os.environ.get('ORDERS_PORT', '50053')}"
SUPPORT_ADDR = f"{HOST}:{os.environ.get('SUPPORT_PORT', '50054')}"
FRONTEND_URL = f"http://{HOST}:{os.environ.get('FRONTEND_PORT', '3000')}"
REDIS_URL = os.environ.get(
    "SMOKE_REDIS_URL", f"redis://{HOST}:{os.environ.get('REDIS_PORT', '6379')}/0"
)
SELLER_EMAIL = "seller@stand.local"
SELLER_PASSWORD = os.environ.get("SEED_SELLER_PASSWORD", "seller-password")

PASSWORD = "smoke-password-1"
# Доставка — 4 шага по FULFILLMENT_STEP_MS (2 с) плюс запас
DELIVERY_TIMEOUT_S = 30.0
# Приветствие оператора — через SUPPORT_AGENT_DELAY_MS (1,5 с) плюс запас
CHAT_READ_TIMEOUT_S = 10.0

Metadata = tuple[tuple[str, str], ...]


def service_metadata() -> Metadata:
    return (("x-api-key", API_KEY),)


def user_metadata(token: str, *extra: tuple[str, str]) -> Metadata:
    return (("x-api-key", API_KEY), ("authorization", f"Bearer {token}"), *extra)


async def sign_in(email: str, password: str) -> str:
    async with grpc.aio.insecure_channel(USERS_ADDR) as channel:
        users = users_pb2_grpc.UserServiceStub(channel)
        response = await users.SignIn(
            users_pb2.SignInRequest(email=email, password=password), metadata=service_metadata()
        )
    assert response.access_token
    return response.access_token


async def sign_up_buyer() -> str:
    """SignUp → код из Redis → ConfirmEmail → SignIn; возвращает токен покупателя."""
    email = f"smoke-{uuid.uuid4().hex[:12]}@stand.local"
    async with grpc.aio.insecure_channel(USERS_ADDR) as channel:
        users = users_pb2_grpc.UserServiceStub(channel)
        signed_up = await users.SignUp(
            users_pb2.SignUpRequest(
                email=email,
                password=PASSWORD,
                display_name="Smoke Buyer",
                role=users_pb2.USER_ROLE_BUYER,
            ),
            metadata=service_metadata(),
        )
        assert signed_up.user.status == users_pb2.USER_STATUS_PENDING

        redis = redis_asyncio.from_url(REDIS_URL, decode_responses=True)
        try:
            code = await redis.get(f"confirm:{email}")
        finally:
            await redis.aclose()
        assert code, "код подтверждения не найден в Redis"

        confirmed = await users.ConfirmEmail(
            users_pb2.ConfirmEmailRequest(email=email, code=str(code)),
            metadata=service_metadata(),
        )
        assert confirmed.user.status == users_pb2.USER_STATUS_ACTIVE
    return await sign_in(email, PASSWORD)


# Async-стабы (`...AsyncStub`) есть только в .pyi, поэтому аннотации с ними — строкой
async def wait_delivered(
    orders: "orders_pb2_grpc.OrderServiceAsyncStub", token: str, order_id: str
) -> None:
    statuses: list[orders_pb2.OrderStatus.ValueType] = []

    async def track() -> None:
        call = orders.TrackOrder(
            orders_pb2.TrackOrderRequest(order_id=order_id), metadata=user_metadata(token)
        )
        async for update in call:
            statuses.append(update.status)
            if update.status == orders_pb2.ORDER_STATUS_DELIVERED:
                call.cancel()
                return

    await asyncio.wait_for(track(), DELIVERY_TIMEOUT_S)
    assert statuses[-1] == orders_pb2.ORDER_STATUS_DELIVERED
    assert statuses == sorted(statuses), f"статусы идут не по порядку: {statuses}"


async def read_until(
    call: grpc.aio.StreamStreamCall[support_pb2.ChatRequest, support_pb2.ChatResponse],
    author: support_pb2.Author.ValueType,
) -> tuple[list[support_pb2.ChatResponse], support_pb2.ChatMessage]:
    """Читает ответы чата до первого сообщения от `author`."""
    seen: list[support_pb2.ChatResponse] = []
    while True:
        response = await asyncio.wait_for(call.read(), CHAT_READ_TIMEOUT_S)
        assert isinstance(response, support_pb2.ChatResponse), "чат закрылся раньше времени"
        seen.append(response)
        if response.WhichOneof("payload") == "message" and response.message.author == author:
            return seen, response.message


async def chat_about_order(token: str, order_id: str) -> None:
    """Chat: join → приветствие оператора → «где заказ» → ответ бота со статусом."""
    async with grpc.aio.insecure_channel(SUPPORT_ADDR) as channel:
        support = support_pb2_grpc.SupportServiceStub(channel)
        call = support.Chat(metadata=user_metadata(token))
        await call.write(support_pb2.ChatRequest(join=support_pb2.Join(order_id=order_id)))
        joined = await asyncio.wait_for(call.read(), CHAT_READ_TIMEOUT_S)
        assert isinstance(joined, support_pb2.ChatResponse)
        assert joined.WhichOneof("payload") == "joined"
        assert joined.joined.chat_id

        seen, greeting = await read_until(call, support_pb2.AUTHOR_AGENT)
        assert greeting.text
        assert any(item.WhichOneof("payload") == "agent_typing" for item in seen)

        client_message_id = uuid.uuid4().hex
        await call.write(
            support_pb2.ChatRequest(
                message=support_pb2.ClientMessage(
                    client_message_id=client_message_id, text="Где мой заказ?"
                )
            )
        )
        seen, reply = await read_until(call, support_pb2.AUTHOR_BOT)
        acks = [item.ack for item in seen if item.WhichOneof("payload") == "ack"]
        assert [ack.client_message_id for ack in acks] == [client_message_id]
        assert order_id in reply.text
        assert "доставлен" in reply.text
        await call.done_writing()
        call.cancel()


async def test_buyer_flow() -> None:
    """Покупатель: регистрация, поиск, корзина, идемпотентный Checkout, доставка, чат."""
    token = await sign_up_buyer()

    async with grpc.aio.insecure_channel(CATALOG_ADDR) as channel:
        catalog = catalog_pb2_grpc.CatalogServiceStub(channel)
        found = await catalog.SearchProducts(
            catalog_pb2.SearchProductsRequest(query="Книга"), metadata=user_metadata(token)
        )
    in_stock = [product for product in found.products if product.stock > 0]
    assert in_stock, "в каталоге нет книг в наличии"
    product = max(in_stock, key=lambda item: item.stock)

    async with grpc.aio.insecure_channel(ORDERS_ADDR) as channel:
        orders = orders_pb2_grpc.OrderServiceStub(channel)
        added = await orders.AddCartItem(
            orders_pb2.AddCartItemRequest(product_id=product.product_id, quantity=1),
            metadata=user_metadata(token),
        )
        assert [item.product_id for item in added.cart.items] == [product.product_id]

        key = ("idempotency-key", uuid.uuid4().hex)
        first = await orders.Checkout(
            orders_pb2.CheckoutRequest(), metadata=user_metadata(token, key)
        )
        repeated = await orders.Checkout(
            orders_pb2.CheckoutRequest(), metadata=user_metadata(token, key)
        )
        order_id = first.order.order_id
        assert order_id
        assert repeated.order.order_id == order_id

        await wait_delivered(orders, token, order_id)

    await chat_about_order(token, order_id)


async def import_rows(
    rows: Sequence[catalog_pb2.ImportRow],
) -> AsyncIterator[catalog_pb2.ImportProductsRequest]:
    yield catalog_pb2.ImportProductsRequest(
        header=catalog_pb2.ImportHeader(mode=catalog_pb2.IMPORT_MODE_UPSERT)
    )
    for row in rows:
        yield catalog_pb2.ImportProductsRequest(row=row)


async def test_seller_import_export() -> None:
    """Продавец: ImportProducts с плохой строкой → отчёт → ExportProducts содержит импорт."""
    token = await sign_in(SELLER_EMAIL, SELLER_PASSWORD)
    suffix = uuid.uuid4().hex[:8]
    good = catalog_pb2.ImportRow(
        offer_id=f"SMOKE-{suffix}",
        name=f"Smoke товар {suffix}",
        category="smoke",
        price_kopecks=10000,
        stock=3,
    )
    bad = catalog_pb2.ImportRow(
        offer_id=f"SMOKE-BAD-{suffix}", name="Без цены", category="smoke", price_kopecks=0
    )
    since = Timestamp()
    since.GetCurrentTime()
    since.seconds -= 1

    async with grpc.aio.insecure_channel(CATALOG_ADDR) as channel:
        catalog = catalog_pb2_grpc.CatalogServiceStub(channel)
        report = await catalog.ImportProducts(
            import_rows([good, bad]), metadata=user_metadata(token)
        )
        assert report.created == 1
        assert report.failed == 1
        assert [(error.row_number, error.field) for error in report.errors] == [
            (2, "price_kopecks")
        ]

        exported = [
            item.product.offer_id
            async for item in catalog.ExportProducts(
                catalog_pb2.ExportProductsRequest(updated_since=since),
                metadata=user_metadata(token),
            )
        ]
    assert good.offer_id in exported
    assert bad.offer_id not in exported


async def test_without_api_key_is_unauthenticated() -> None:
    async with grpc.aio.insecure_channel(CATALOG_ADDR) as channel:
        catalog = catalog_pb2_grpc.CatalogServiceStub(channel)
        with pytest.raises(grpc.aio.AioRpcError) as raised:
            await catalog.SearchProducts(catalog_pb2.SearchProductsRequest(query="Книга"))
    assert raised.value.code() == grpc.StatusCode.UNAUTHENTICATED


async def test_seller_method_as_buyer_is_permission_denied() -> None:
    token = await sign_up_buyer()
    row = catalog_pb2.ImportRow(
        offer_id="SMOKE-DENIED", name="Нельзя", category="smoke", price_kopecks=100, stock=1
    )
    async with grpc.aio.insecure_channel(CATALOG_ADDR) as channel:
        catalog = catalog_pb2_grpc.CatalogServiceStub(channel)
        with pytest.raises(grpc.aio.AioRpcError) as raised:
            await catalog.ImportProducts(import_rows([row]), metadata=user_metadata(token))
    assert raised.value.code() == grpc.StatusCode.PERMISSION_DENIED


def test_reflection_lists_catalog_v1_and_v2() -> None:
    with grpc.insecure_channel(CATALOG_ADDR) as channel:
        services = set(ProtoReflectionDescriptorDatabase(channel).get_services())
    assert {"catalog.v1.CatalogService", "catalog.v2.CatalogService"} <= services


def test_frontend_serves_spa() -> None:
    reply = httpx.get(f"{FRONTEND_URL}/")
    assert reply.status_code == 200
    assert reply.headers["content-type"].startswith("text/html")
    assert '<div id="app">' in reply.text


def test_frontend_deep_link_serves_index_html() -> None:
    root = httpx.get(f"{FRONTEND_URL}/")
    deep = httpx.get(f"{FRONTEND_URL}/orders/x")
    assert deep.status_code == 200
    assert deep.text == root.text


def test_frontend_proxies_api_to_gateway() -> None:
    health = httpx.get(f"{FRONTEND_URL}/api/healthz")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    products = httpx.get(f"{FRONTEND_URL}/api/products")
    assert products.status_code == 200
    assert products.json()["products"]
