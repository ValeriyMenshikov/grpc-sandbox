"""OrdersClient против поддельного order-service: проброс authorization и x-request-id, ошибки."""

import asyncio
from collections.abc import AsyncIterator, Iterator

import grpc
import pytest
from stand_core.grpc import DependencyUnavailable
from stand_core.grpc.context import (
    reset_authorization,
    reset_request_id,
    reset_time_remaining,
    set_authorization,
    set_request_id,
    set_time_remaining,
)
from stand_core.settings import Settings
from support.v1 import support_pb2
from support_service.bot import STATUS_UNAVAILABLE
from support_service.orders_client import OrdersClient

from .conftest import API_KEY
from .fakes import FakeRepository
from .harness import BUYER, BUYER_TOKEN, running_support
from .neighbour import Seen, fake_orders

WAIT_S = 2.0


@pytest.fixture
async def seen(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Seen]:
    async with fake_orders() as (server, seen):
        monkeypatch.setenv("ORDERS_ADDR", f"localhost:{server.port}")
        yield seen


@pytest.fixture
async def client(seen: Seen) -> AsyncIterator[OrdersClient]:
    client = OrdersClient(Settings())
    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture
def as_buyer() -> Iterator[None]:
    """Контекст входящего вызова покупателя: его authorization и request id."""
    authorization = set_authorization(f"Bearer {BUYER_TOKEN}")
    request_id = set_request_id("req-1")
    yield
    reset_request_id(request_id)
    reset_authorization(authorization)


@pytest.mark.usefixtures("as_buyer")
async def test_get_order_forwards_user_authorization(client: OrdersClient, seen: Seen) -> None:
    found = await client.get_order("o-1")

    assert found is not None
    assert found.order_id == "o-1"
    metadata = seen.metadata[-1]
    assert metadata["authorization"] == f"Bearer {BUYER_TOKEN}"
    assert metadata["x-request-id"] == "req-1"
    assert metadata["x-api-key"] == API_KEY


@pytest.mark.usefixtures("as_buyer")
async def test_foreign_and_missing_orders_are_none(client: OrdersClient) -> None:
    assert await client.get_order("o-2") is None
    assert await client.get_order("missing") is None


@pytest.mark.usefixtures("as_buyer")
async def test_unavailable_orders_raise_dependency_unavailable(
    client: OrdersClient, seen: Seen
) -> None:
    seen.down = True

    with pytest.raises(DependencyUnavailable) as info:
        await client.get_order("o-1")

    assert info.value.dependency == "orders"


async def test_unreachable_orders_are_dependency_unavailable(client: OrdersClient) -> None:
    # Порт, на котором никто не слушает: order-service остановлен
    await client.disconnect()
    client._channel = grpc.aio.insecure_channel("localhost:1")
    try:
        with pytest.raises(DependencyUnavailable):
            await client.get_order("o-1")
    finally:
        await client.disconnect()


async def test_long_chat_deadline_is_capped(client: OrdersClient, seen: Seen) -> None:
    token = set_time_remaining(600)
    try:
        await client.get_order("missing")
    finally:
        reset_time_remaining(token)

    remaining = seen.time_remaining[-1]
    assert remaining is not None
    assert remaining <= Settings().grpc_default_deadline_seconds + 0.1


async def test_chat_bot_reaches_orders_with_user_context(
    seen: Seen, repository: FakeRepository
) -> None:
    async with running_support(repository) as stub:
        call = stub.Chat(metadata=(*BUYER, ("x-request-id", "req-chat")))
        await call.write(support_pb2.ChatRequest(join=support_pb2.Join(order_id="o-1")))
        joined = await asyncio.wait_for(call.read(), WAIT_S)
        await call.write(support_pb2.ChatRequest(message=support_pb2.ClientMessage(text="статус?")))
        replies = [await asyncio.wait_for(call.read(), WAIT_S) for _ in range(2)]
        seen.down = True
        await call.write(
            support_pb2.ChatRequest(message=support_pb2.ClientMessage(text="а где он?"))
        )
        after = [await asyncio.wait_for(call.read(), WAIT_S) for _ in range(2)]
        call.cancel()

    assert isinstance(joined, support_pb2.ChatResponse)
    assert joined.HasField("joined")
    bot = replies[1]
    assert isinstance(bot, support_pb2.ChatResponse)
    assert bot.message.text == "Заказ o-1: передан курьеру"
    # И проверка заказа при join, и бот шли от имени покупателя с request id чата
    assert len(seen.metadata) == 3
    for metadata in seen.metadata:
        assert metadata["authorization"] == f"Bearer {BUYER_TOKEN}"
        assert metadata["x-request-id"] == "req-chat"
    unavailable = after[1]
    assert isinstance(unavailable, support_pb2.ChatResponse)
    assert unavailable.message.text == STATUS_UNAVAILABLE
