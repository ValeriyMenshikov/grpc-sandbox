"""order-service целиком на in-process сервере; клиенты к соседям — через DI.override."""

from collections.abc import AsyncIterator, Iterator

import grpc
import order_service.handlers  # noqa: F401  — регистрирует хэндлеры
import pytest
from google.rpc import error_details_pb2
from nuke_di import Dependencies
from order_service.auth import AUTH_POLICIES
from order_service.carts import Carts
from order_service.catalog_client import CatalogClient
from order_service.events import OrderEvents
from order_service.fulfillment import Fulfillment
from order_service.idempotency import IdempotencyKeys
from order_service.models import OrderStatus
from order_service.repository import OrderRepository
from order_service.settings import OrderSettings
from order_service.stock_client import StockClient
from order_service.users_client import UsersClient
from orders.v1 import orders_pb2
from orders.v1 import orders_pb2_grpc as orders_grpc
from stand_core.clients import Sessions
from stand_core.grpc import GRPC_HANDLERS, CurrentUser, DependencyUnavailable, Role, inject_handlers
from stand_core.grpc.interceptors import AUTH_POLICIES as REGISTERED_POLICIES
from stand_core.grpc.interceptors import (
    AuthInterceptor,
    ExceptionHandlingInterceptor,
    LoggingInterceptor,
    RequestIdInterceptor,
    StreamCountInterceptor,
    register_auth_policies,
)
from stand_core.grpc.server import grpc_server
from stand_core.settings import Settings
from stand_core.testing import rich_status

from .conftest import API_KEY
from .fakes import (
    BUYER_ID,
    OTHER_ID,
    FakeCarts,
    FakeCatalog,
    FakeEvents,
    FakeIdempotency,
    FakeRepository,
    FakeStock,
    FakeUsers,
)

BUYER_TOKEN = "buyer-token"
BUYER = (("x-api-key", API_KEY), ("authorization", f"Bearer {BUYER_TOKEN}"))
# OrderServiceAsyncStub есть только в .pyi, поэтому аннотации с ним — строкой


def with_key(key: str) -> tuple[tuple[str, str], ...]:
    return (*BUYER, ("idempotency-key", key))


class FakeSessions(Sessions):
    def __init__(self) -> None:
        pass

    async def get(self, token: str) -> CurrentUser | None:
        return CurrentUser(BUYER_ID, Role.BUYER) if token == BUYER_TOKEN else None


@pytest.fixture
def policies() -> Iterator[None]:
    saved = dict(REGISTERED_POLICIES)
    register_auth_policies(AUTH_POLICIES)
    yield
    REGISTERED_POLICIES.clear()
    REGISTERED_POLICIES.update(saved)


@pytest.fixture
async def stub(
    repository: FakeRepository,
    carts: FakeCarts,
    idempotency: FakeIdempotency,
    stock: FakeStock,
    catalog: FakeCatalog,
    events: FakeEvents,
    users: FakeUsers,
    policies: None,
) -> AsyncIterator["orders_grpc.OrderServiceAsyncStub"]:
    container = Dependencies()
    container.mock(OrderRepository, repository)
    container.mock(Carts, carts)
    container.mock(IdempotencyKeys, idempotency)
    container.mock(OrderEvents, events)
    sessions = FakeSessions()
    interceptors = [
        RequestIdInterceptor(),
        LoggingInterceptor(),
        AuthInterceptor(Settings(), sessions),
        StreamCountInterceptor(),
        ExceptionHandlingInterceptor(),
    ]
    with (
        container.override(StockClient, stock),
        container.override(CatalogClient, catalog),
        container.override(UsersClient, users),
    ):
        handlers = inject_handlers(
            {s: a for s, a in GRPC_HANDLERS.items() if s.package == "orders.v1"}, container
        )
        async with (
            container,
            grpc_server(handlers, interceptors, port=0, host="localhost", grace=0) as server,
            grpc.aio.insecure_channel(f"localhost:{server.port}") as channel,
        ):
            yield orders_grpc.OrderServiceStub(channel)


async def test_cart_checkout_get_list_and_cancel(
    stub: "orders_grpc.OrderServiceAsyncStub", stock: FakeStock
) -> None:
    await stub.AddCartItem(
        orders_pb2.AddCartItemRequest(product_id="p-1", quantity=2), metadata=BUYER
    )
    cart = await stub.GetCart(orders_pb2.GetCartRequest(), metadata=BUYER)

    checkout = await stub.Checkout(orders_pb2.CheckoutRequest(), metadata=with_key("k-1"))
    replay = await stub.Checkout(orders_pb2.CheckoutRequest(), metadata=with_key("k-1"))
    order_id = checkout.order.order_id
    got = await stub.GetOrder(orders_pb2.GetOrderRequest(order_id=order_id), metadata=BUYER)
    listed = await stub.ListOrders(orders_pb2.ListOrdersRequest(), metadata=BUYER)
    cancelled = await stub.CancelOrder(
        orders_pb2.CancelOrderRequest(order_id=order_id), metadata=BUYER
    )
    empty_cart = await stub.GetCart(orders_pb2.GetCartRequest(), metadata=BUYER)

    assert cart.cart.total.units == 3999
    assert replay.order.order_id == order_id
    assert got.order.status == orders_pb2.ORDER_STATUS_CREATED
    assert [order.order_id for order in listed.orders] == [order_id]
    assert cancelled.order.status == orders_pb2.ORDER_STATUS_CANCELLED
    assert stock.released == [order_id]
    assert stock.available["p-1"] == 10
    assert list(empty_cart.cart.items) == []


async def test_checkout_without_key_is_invalid_argument(
    stub: "orders_grpc.OrderServiceAsyncStub", carts: FakeCarts
) -> None:
    carts.carts[BUYER_ID] = {"p-1": 1}

    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stub.Checkout(orders_pb2.CheckoutRequest(), metadata=BUYER)

    assert info.value.code() is grpc.StatusCode.INVALID_ARGUMENT
    bad_request = error_details_pb2.BadRequest()
    assert rich_status(info.value).details[0].Unpack(bad_request)
    assert bad_request.field_violations[0].field == "idempotency-key"


async def test_checkout_with_catalog_unavailable_is_unavailable(
    stub: "orders_grpc.OrderServiceAsyncStub",
    carts: FakeCarts,
    stock: FakeStock,
    repository: FakeRepository,
) -> None:
    carts.carts[BUYER_ID] = {"p-1": 1}
    stock.error = DependencyUnavailable("catalog")

    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stub.Checkout(orders_pb2.CheckoutRequest(), metadata=with_key("k-1"))

    assert info.value.code() is grpc.StatusCode.UNAVAILABLE
    assert repository.orders == {}


async def test_empty_cart_and_shortage_are_failed_precondition(
    stub: "orders_grpc.OrderServiceAsyncStub", carts: FakeCarts
) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as empty:
        await stub.Checkout(orders_pb2.CheckoutRequest(), metadata=with_key("k-1"))
    carts.carts[BUYER_ID] = {"p-2": 4}
    with pytest.raises(grpc.aio.AioRpcError) as shortage:
        await stub.Checkout(orders_pb2.CheckoutRequest(), metadata=with_key("k-1"))

    assert empty.value.code() is grpc.StatusCode.FAILED_PRECONDITION
    assert shortage.value.code() is grpc.StatusCode.FAILED_PRECONDITION
    failure = error_details_pb2.PreconditionFailure()
    assert rich_status(shortage.value).details[0].Unpack(failure)
    assert failure.violations[0].subject == "product:p-2"


async def test_foreign_order_is_not_found(
    stub: "orders_grpc.OrderServiceAsyncStub", repository: FakeRepository
) -> None:
    order = repository.add(user_id=OTHER_ID)

    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stub.GetOrder(orders_pb2.GetOrderRequest(order_id=order.order_id), metadata=BUYER)

    assert info.value.code() is grpc.StatusCode.NOT_FOUND


async def test_cancel_after_courier_is_failed_precondition(
    stub: "orders_grpc.OrderServiceAsyncStub", repository: FakeRepository
) -> None:
    order = repository.add(status=OrderStatus.HANDED_TO_COURIER)

    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stub.CancelOrder(
            orders_pb2.CancelOrderRequest(order_id=order.order_id), metadata=BUYER
        )

    assert info.value.code() is grpc.StatusCode.FAILED_PRECONDITION


async def test_without_token_is_unauthenticated(stub: "orders_grpc.OrderServiceAsyncStub") -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stub.GetCart(orders_pb2.GetCartRequest(), metadata=(("x-api-key", API_KEY),))

    assert info.value.code() is grpc.StatusCode.UNAUTHENTICATED


async def test_track_order_streams_until_delivered_with_items_count(
    stub: "orders_grpc.OrderServiceAsyncStub", repository: FakeRepository, events: FakeEvents
) -> None:
    order = repository.add()
    fulfillment = Fulfillment(repository, events, OrderSettings())
    call = stub.TrackOrder(orders_pb2.TrackOrderRequest(order_id=order.order_id), metadata=BUYER)

    first = await call.read()
    for _ in range(4):
        await fulfillment.advance()
    rest: list[orders_pb2.TrackOrderResponse] = []
    # read() и async for на одном вызове смешивать нельзя
    while isinstance(message := await call.read(), orders_pb2.TrackOrderResponse):
        rest.append(message)

    assert isinstance(first, orders_pb2.TrackOrderResponse)
    assert first.status == orders_pb2.ORDER_STATUS_CREATED
    assert [message.status for message in rest] == [
        orders_pb2.ORDER_STATUS_PAID,
        orders_pb2.ORDER_STATUS_ASSEMBLING,
        orders_pb2.ORDER_STATUS_HANDED_TO_COURIER,
        orders_pb2.ORDER_STATUS_DELIVERED,
    ]
    assert await call.code() is grpc.StatusCode.OK
    assert ("x-items-count", "5") in tuple(await call.trailing_metadata())


async def test_track_foreign_order_is_not_found(
    stub: "orders_grpc.OrderServiceAsyncStub", repository: FakeRepository
) -> None:
    order = repository.add(user_id=OTHER_ID)
    call = stub.TrackOrder(orders_pb2.TrackOrderRequest(order_id=order.order_id), metadata=BUYER)

    with pytest.raises(grpc.aio.AioRpcError) as info:
        await call.read()

    assert info.value.code() is grpc.StatusCode.NOT_FOUND
