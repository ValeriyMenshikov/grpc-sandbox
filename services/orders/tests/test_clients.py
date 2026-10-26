"""Клиенты к catalog против поддельного catalog-service и хранилища поверх замоканного Redis."""

from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, Mock

import grpc
import pytest
from google.rpc import error_details_pb2
from nuke_di import Dependencies
from order_service.carts import Carts
from order_service.catalog_client import CatalogClient
from order_service.handlers.checkout_u_u import checkout
from order_service.idempotency import IdempotencyKeys, IdempotencyRecord
from order_service.repository import OrderRepository
from order_service.stock_client import StockClient
from order_service.users_client import UsersClient
from orders.v1 import orders_pb2
from stand_core.clients import Rabbit, Sessions
from stand_core.grpc import (
    CurrentUser,
    DependencyUnavailable,
    FailedPrecondition,
    MethodSignature,
    Role,
    inject_handlers,
)
from stand_core.grpc.context import reset_time_remaining, set_time_remaining
from stand_core.grpc.interceptors import (
    AUTH_POLICIES as REGISTERED_POLICIES,
)
from stand_core.grpc.interceptors import (
    AuthInterceptor,
    AuthPolicy,
    ExceptionHandlingInterceptor,
    RequestIdInterceptor,
    register_auth_policies,
)
from stand_core.grpc.rpc import annotate
from stand_core.grpc.server import grpc_server
from stand_core.settings import Settings
from stand_core.testing import rich_status

from .conftest import API_KEY
from .fakes import (
    BUYER_ID,
    FakeCarts,
    FakeIdempotency,
    FakeRabbit,
    FakeRepository,
    FakeUsers,
)
from .neighbour import Seen, fake_catalog

# grpc округляет timeout вверх при передаче по сети: сосед видит чуть больше отправленного
WIRE_SLACK = 0.1


@pytest.fixture
async def seen(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Seen]:
    async with fake_catalog() as (server, seen):
        monkeypatch.setenv("CATALOG_ADDR", f"localhost:{server.port}")
        yield seen


@pytest.fixture
async def stock_client(seen: Seen) -> AsyncIterator[StockClient]:
    client = StockClient(Settings())
    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture
async def catalog_client(seen: Seen) -> AsyncIterator[CatalogClient]:
    client = CatalogClient(Settings())
    await client.connect()
    yield client
    await client.disconnect()


async def test_get_product_and_missing_product(catalog_client: CatalogClient, seen: Seen) -> None:
    found = await catalog_client.get_product("p-1")
    missing = await catalog_client.get_product("missing")
    products = await catalog_client.get_products(["p-1", "missing", "p-2", "p-1"])

    assert found is not None
    assert found.name == "Наушники"
    assert missing is None
    assert list(products) == ["p-1", "p-2"]
    assert seen.metadata["x-api-key"] == API_KEY
    assert "authorization" not in seen.metadata


async def test_get_product_when_catalog_is_broken(
    catalog_client: CatalogClient, seen: Seen
) -> None:
    seen.down = True

    with pytest.raises(DependencyUnavailable):
        await catalog_client.get_product("p-1")
    # Параллельные GetProduct: ошибка соседа как есть, не ExceptionGroup
    with pytest.raises(DependencyUnavailable):
        await catalog_client.get_products(["p-1", "p-2"])


async def test_reserve_and_release(stock_client: StockClient, seen: Seen) -> None:
    await stock_client.reserve("o-1", {"p-1": 2})
    released = await stock_client.release("o-1")
    again = await stock_client.release("o-1")

    assert (released, again) == (True, False)
    assert seen.released == ["o-1", "o-1"]


async def test_shortage_keeps_catalog_details(stock_client: StockClient) -> None:
    with pytest.raises(FailedPrecondition) as info:
        await stock_client.reserve("o-1", {"p-1": 1, "p-2": 1, "nope": 1})

    assert info.value.message == "Not enough stock"
    assert [(v.type, v.subject) for v in info.value.violations] == [
        ("INSUFFICIENT_STOCK", "product:p-2"),
        ("PRODUCT_NOT_FOUND", "product:nope"),
    ]


async def test_unreachable_catalog_is_dependency_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CATALOG_ADDR", "localhost:1")
    client = StockClient(Settings())
    await client.connect()
    try:
        with pytest.raises(DependencyUnavailable) as info:
            await client.reserve("o-1", {"p-1": 1})
        # Тихое снятие резерва не бросает
        await client.release_quietly("o-1")
    finally:
        await client.disconnect()

    assert info.value.dependency == "catalog"


async def test_unreachable_users_gives_empty_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USERS_ADDR", "localhost:1")
    client = UsersClient(Settings())
    await client.connect()
    try:
        assert await client.email() == ""
    finally:
        await client.disconnect()


async def test_carts_use_hash_per_user() -> None:
    redis = Mock()
    redis.client.hgetall = AsyncMock(return_value={"p-1": "2", "p-2": "1"})
    redis.client.eval = AsyncMock(side_effect=[3, -1])
    redis.client.hdel = AsyncMock(side_effect=[1, 0])
    redis.client.delete = AsyncMock()
    carts = Carts(redis)

    items = await carts.items("u1")
    added = [await carts.add("u1", "p-1", 3), await carts.add("u1", "p-1", 10_000)]
    removed = [await carts.remove("u1", "p-1"), await carts.remove("u1", "p-1")]
    await carts.clear("u1")

    assert items == {"p-1": 2, "p-2": 1}
    assert added == [True, False]
    assert redis.client.eval.await_args_list[0].args[1:] == (1, "cart:u1", "p-1", "3", "10000")
    assert removed == [True, False]
    redis.client.delete.assert_awaited_once_with("cart:u1")


async def test_idempotency_keys_pending_then_committed() -> None:
    redis = Mock()
    redis.client.set = AsyncMock(side_effect=[True, None])
    redis.client.get = AsyncMock(side_effect=["pending:o-1", "o-1", None])
    redis.client.eval = AsyncMock(side_effect=["OK", 1])
    keys = IdempotencyKeys(redis)

    claimed = [await keys.claim("u1", "k", "o-1"), await keys.claim("u1", "k", "o-2")]
    records = [await keys.get("u1", "k") for _ in range(3)]
    committed = await keys.commit("u1", "k", "o-1", 86400)
    await keys.forget("u1", "k", IdempotencyRecord("o-1", False))

    assert claimed == [True, False]
    redis.client.set.assert_any_await("idem:u1:k", "pending:o-1", nx=True, ex=30)
    assert records == [IdempotencyRecord("o-1", True), IdempotencyRecord("o-1", False), None]
    assert committed is True
    # commit и forget — compare-and-set: меняют ключ, только если в нём значение этого вызова
    commit_call, forget_call = redis.client.eval.await_args_list
    assert commit_call.args[1:] == (1, "idem:u1:k", "pending:o-1", "o-1", "86400")
    assert forget_call.args[1:] == (1, "idem:u1:k", "o-1")


async def test_idempotency_pending_ttl_covers_deadline() -> None:
    redis = Mock()
    redis.client.set = AsyncMock(return_value=True)
    keys = IdempotencyKeys(redis)

    token = set_time_remaining(60.0)
    try:
        await keys.claim("u1", "k", "o-1")
    finally:
        reset_time_remaining(token)

    assert redis.client.set.await_args.kwargs["ex"] == 90


# --- Checkout целиком: входящий вызов → order-service → поддельный catalog ---

CHECKOUT = MethodSignature("Checkout", "OrderService", "orders.v1")
TOKEN = "buyer-token"


class FakeSessions(Sessions):
    def __init__(self) -> None:
        pass

    async def get(self, token: str) -> CurrentUser | None:
        return CurrentUser(BUYER_ID, Role.BUYER) if token == TOKEN else None


@pytest.fixture
def policies() -> Iterator[None]:
    saved = dict(REGISTERED_POLICIES)
    register_auth_policies({CHECKOUT.full_method: AuthPolicy.USER})
    yield
    REGISTERED_POLICIES.clear()
    REGISTERED_POLICIES.update(saved)


@pytest.fixture
def carts() -> FakeCarts:
    carts = FakeCarts()
    carts.carts[BUYER_ID] = {"p-1": 2}
    return carts


@pytest.fixture
async def orders_channel(
    seen: Seen, carts: FakeCarts, repository: FakeRepository, policies: None
) -> AsyncIterator[grpc.aio.Channel]:
    """order-service с настоящими StockClient и CatalogClient; Redis и Postgres подменены."""
    container = Dependencies()
    container.mock(Carts, carts)
    container.mock(IdempotencyKeys, FakeIdempotency())
    container.mock(OrderRepository, repository)
    container.mock(UsersClient, FakeUsers())
    container.mock(Rabbit, FakeRabbit())
    handlers = inject_handlers({CHECKOUT: annotate(checkout)}, container)
    interceptors = [
        RequestIdInterceptor(),
        AuthInterceptor(Settings(), FakeSessions()),
        ExceptionHandlingInterceptor(),
    ]
    async with (
        container,
        grpc_server(handlers, interceptors, port=0, host="localhost", grace=0) as server,
        grpc.aio.insecure_channel(f"localhost:{server.port}") as channel,
    ):
        yield channel


async def call_checkout(
    channel: grpc.aio.Channel, key: str, deadline: float | None = None
) -> orders_pb2.CheckoutResponse:
    method = channel.unary_unary(
        CHECKOUT.full_method,
        request_serializer=orders_pb2.CheckoutRequest.SerializeToString,
        response_deserializer=orders_pb2.CheckoutResponse.FromString,
    )
    response: orders_pb2.CheckoutResponse = await method(
        orders_pb2.CheckoutRequest(),
        metadata=(
            ("x-api-key", API_KEY),
            ("authorization", f"Bearer {TOKEN}"),
            ("x-request-id", "rid-checkout"),
            ("idempotency-key", key),
        ),
        timeout=deadline,
    )
    return response


async def test_checkout_forwards_deadline_and_request_id_to_reserve(
    orders_channel: grpc.aio.Channel, seen: Seen, carts: FakeCarts
) -> None:
    response = await call_checkout(orders_channel, "k-1", deadline=2)

    assert list(seen.reserved) == [response.order.order_id]
    assert seen.metadata["x-request-id"] == "rid-checkout"
    assert seen.metadata["x-api-key"] == API_KEY
    assert seen.time_remaining is not None
    assert 1 < seen.time_remaining <= 2 + WIRE_SLACK
    assert response.order.items[0].unit_price.units == 1999
    assert carts.carts == {}


async def test_checkout_shortage_has_catalog_details_on_the_wire(
    orders_channel: grpc.aio.Channel, carts: FakeCarts, repository: FakeRepository
) -> None:
    carts.carts[BUYER_ID] = {"p-2": 1}

    with pytest.raises(grpc.aio.AioRpcError) as info:
        await call_checkout(orders_channel, "k-1")

    assert info.value.code() is grpc.StatusCode.FAILED_PRECONDITION
    failure = error_details_pb2.PreconditionFailure()
    assert rich_status(info.value).details[0].Unpack(failure)
    assert [(v.type, v.subject) for v in failure.violations] == [
        ("INSUFFICIENT_STOCK", "product:p-2")
    ]
    assert repository.orders == {}


async def test_slow_catalog_is_unavailable_without_order(
    orders_channel: grpc.aio.Channel, seen: Seen, repository: FakeRepository
) -> None:
    seen.delay = 1.0

    with pytest.raises(grpc.aio.AioRpcError) as info:
        await call_checkout(orders_channel, "k-1", deadline=0.3)

    # Клиент видит либо свой DEADLINE_EXCEEDED, либо UNAVAILABLE от order-service — заказа нет
    assert info.value.code() in {grpc.StatusCode.DEADLINE_EXCEEDED, grpc.StatusCode.UNAVAILABLE}
    assert repository.orders == {}


async def test_catalog_down_is_unavailable(
    orders_channel: grpc.aio.Channel, seen: Seen, repository: FakeRepository
) -> None:
    seen.down = True

    with pytest.raises(grpc.aio.AioRpcError) as info:
        await call_checkout(orders_channel, "k-1")

    assert info.value.code() is grpc.StatusCode.UNAVAILABLE
    error_info = error_details_pb2.ErrorInfo()
    assert rich_status(info.value).details[0].Unpack(error_info)
    assert (error_info.reason, error_info.metadata["dependency"]) == (
        "DEPENDENCY_UNAVAILABLE",
        "catalog",
    )
    assert repository.orders == {}
