"""Базовый клиент к соседям: проброс контекста вызова и UNAVAILABLE/DEADLINE_EXCEEDED."""

import asyncio
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import grpc
import pytest
from catalog.v1 import catalog_pb2
from google.rpc import error_details_pb2
from nuke_di import Dependencies
from stand_core import Context
from stand_core.clients import GrpcClient
from stand_core.clients.sessions import Sessions
from stand_core.grpc.context import CurrentUser, Role
from stand_core.grpc.di import inject_handlers, resolve_interceptors
from stand_core.grpc.errors import DependencyUnavailable, NotFound
from stand_core.grpc.interceptors import (
    AuthInterceptor,
    ExceptionHandlingInterceptor,
    RequestIdInterceptor,
)
from stand_core.grpc.rpc import MethodSignature, annotate
from stand_core.grpc.server import RunningServer, grpc_server
from stand_core.settings import Settings

from .rich_status import rich_status

API_KEY = "client-key"
# grpc округляет timeout вверх при передаче по сети: сосед видит чуть больше отправленного
WIRE_SLACK = 0.1
GET_STOCK = "/catalog.v1.StockService/GetStock"


class StockClient(GrpcClient):
    address_env = "TEST_STOCK_ADDR"
    dependency = "catalog"

    async def get_stock(
        self, product_id: str, *, deadline: float | None = None
    ) -> catalog_pb2.GetStockResponse:
        return await self.unary(
            GET_STOCK,
            catalog_pb2.GetStockRequest(product_id=product_id),
            catalog_pb2.GetStockResponse,
            forward_authorization=True,
            deadline=deadline,
        )


@dataclass
class Seen:
    """Что увидел сосед: metadata и остаток deadline."""

    metadata: dict[str, str] = field(default_factory=dict)
    time_remaining: float | None = None


SEEN = Seen()


async def get_stock(
    request: catalog_pb2.GetStockRequest, context: Context
) -> catalog_pb2.GetStockResponse:
    SEEN.metadata = {
        key: value for key, value in context.invocation_metadata() or () if isinstance(value, str)
    }
    SEEN.time_remaining = context.time_remaining()
    if request.product_id == "slow":
        await asyncio.sleep(1)
    if request.product_id == "down":
        raise DependencyUnavailable("postgres")
    if request.product_id == "missing":
        raise NotFound("product", "missing")
    return catalog_pb2.GetStockResponse(product_id=request.product_id, available=7)


async def get_product(
    request: catalog_pb2.GetProductRequest, context: Context, stock: StockClient
) -> catalog_pb2.GetProductResponse:
    """Хэндлер «сервиса-фронта», который ходит к соседу."""
    response = await stock.get_stock(request.product_id)
    return catalog_pb2.GetProductResponse(
        product=catalog_pb2.Product(product_id=response.product_id, stock=response.available)
    )


class FakeSessions(Sessions):
    def __init__(self) -> None:
        pass

    async def get(self, token: str) -> CurrentUser | None:
        return CurrentUser("u1", Role.BUYER) if token == "t1" else None


@pytest.fixture(autouse=True)
def settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAND_API_KEY", API_KEY)
    monkeypatch.setenv("GRPC_DEFAULT_DEADLINE_SECONDS", "3")


@pytest.fixture
async def neighbour(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[RunningServer]:
    """Сосед с ExceptionHandling, чтобы отвечать доменными статусами."""
    handlers = {MethodSignature("GetStock", "StockService", "catalog.v1"): annotate(get_stock)}
    async with grpc_server(
        handlers, [ExceptionHandlingInterceptor()], port=0, host="localhost", grace=0
    ) as server:
        monkeypatch.setenv("TEST_STOCK_ADDR", f"localhost:{server.port}")
        yield server


@pytest.fixture
async def stock(neighbour: RunningServer) -> AsyncIterator[StockClient]:
    client = StockClient(Settings())
    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture
async def front(neighbour: RunningServer) -> AsyncIterator[grpc.aio.Channel]:
    """Сервис со стандартными интерцепторами, хэндлер которого вызывает соседа через StockClient."""
    container = Dependencies()
    container.mock(Sessions, FakeSessions())
    handlers = inject_handlers(
        {MethodSignature("GetProduct", "CatalogService", "catalog.v1"): annotate(get_product)},
        container,
    )
    interceptors = resolve_interceptors(
        [RequestIdInterceptor, AuthInterceptor, ExceptionHandlingInterceptor], container
    )
    async with (
        container,
        grpc_server(handlers, interceptors, port=0, host="localhost", grace=0) as server,
        grpc.aio.insecure_channel(f"localhost:{server.port}") as channel,
    ):
        yield channel


async def call_front(
    channel: grpc.aio.Channel, product_id: str, deadline: float | None = None
) -> catalog_pb2.GetProductResponse:
    method = channel.unary_unary(
        "/catalog.v1.CatalogService/GetProduct",
        request_serializer=catalog_pb2.GetProductRequest.SerializeToString,
        response_deserializer=catalog_pb2.GetProductResponse.FromString,
    )
    response: catalog_pb2.GetProductResponse = await method(
        catalog_pb2.GetProductRequest(product_id=product_id),
        metadata=[
            ("x-api-key", API_KEY),
            ("authorization", "Bearer t1"),
            ("x-request-id", "rid-chain"),
        ],
        timeout=deadline,
    )
    return response


async def test_forwards_request_id_authorization_and_api_key(front: grpc.aio.Channel) -> None:
    response = await call_front(front, "p1")

    assert response.product.stock == 7
    assert SEEN.metadata["x-request-id"] == "rid-chain"
    assert SEEN.metadata["authorization"] == "Bearer t1"
    assert SEEN.metadata["x-api-key"] == API_KEY


async def test_forwards_remaining_deadline(front: grpc.aio.Channel) -> None:
    await call_front(front, "p1", deadline=1.5)

    assert SEEN.time_remaining is not None
    assert 0.5 < SEEN.time_remaining <= 1.5 + WIRE_SLACK


async def test_default_deadline_without_incoming_deadline(front: grpc.aio.Channel) -> None:
    await call_front(front, "p1")

    assert SEEN.time_remaining is not None
    assert 2 < SEEN.time_remaining <= 3 + WIRE_SLACK


async def test_neighbour_unavailable_reaches_caller_as_unavailable(
    front: grpc.aio.Channel,
) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await call_front(front, "down")

    assert info.value.code() is grpc.StatusCode.UNAVAILABLE
    status = rich_status(info.value)
    error_info = error_details_pb2.ErrorInfo()
    status.details[0].Unpack(error_info)
    assert error_info.metadata["dependency"] == "catalog"


async def test_outside_of_call_sends_only_api_key(stock: StockClient) -> None:
    response = await stock.get_stock("p1")

    assert response.available == 7
    assert SEEN.metadata["x-api-key"] == API_KEY
    assert "x-request-id" not in SEEN.metadata
    assert "authorization" not in SEEN.metadata
    assert SEEN.time_remaining is not None
    assert 2 < SEEN.time_remaining <= 3 + WIRE_SLACK


async def test_unavailable_status_becomes_dependency_unavailable(stock: StockClient) -> None:
    with pytest.raises(DependencyUnavailable) as info:
        await stock.get_stock("down")

    assert info.value.dependency == "catalog"
    assert isinstance(info.value.__cause__, grpc.aio.AioRpcError)


async def test_deadline_exceeded_becomes_dependency_unavailable(stock: StockClient) -> None:
    with pytest.raises(DependencyUnavailable, match="DEADLINE_EXCEEDED"):
        await stock.get_stock("slow", deadline=0.05)


async def test_unreachable_neighbour_is_dependency_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with socket.socket() as sock:
        sock.bind(("localhost", 0))
        port = sock.getsockname()[1]
    monkeypatch.setenv("TEST_STOCK_ADDR", f"localhost:{port}")
    client = StockClient(Settings())
    await client.connect()
    try:
        with pytest.raises(DependencyUnavailable, match="UNAVAILABLE"):
            await client.get_stock("p1", deadline=1)
    finally:
        await client.disconnect()


async def test_other_errors_stay_rpc_errors(stock: StockClient) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stock.get_stock("missing")

    assert info.value.code() is grpc.StatusCode.NOT_FOUND


async def test_connect_requires_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_STOCK_ADDR", raising=False)
    client = StockClient(Settings())

    with pytest.raises(RuntimeError, match="TEST_STOCK_ADDR"):
        await client.connect()
    with pytest.raises(RuntimeError, match="not connected"):
        _ = client.channel


def test_client_resolves_without_io() -> None:
    container = Dependencies()

    client = container.resolve(StockClient)

    assert client is container.resolve(StockClient)
    with pytest.raises(RuntimeError, match="not connected"):
        _ = client.channel
