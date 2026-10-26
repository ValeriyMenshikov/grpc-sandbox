"""Chat, GetChatHistory и GetOrderTimeline на in-process сервере; OrdersClient подменён через DI."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import grpc
import pytest
from google.rpc import error_details_pb2
from stand_core.grpc import DependencyUnavailable
from stand_core.testing import rich_status
from support.v1 import support_pb2
from support.v1 import support_pb2_grpc as support_grpc
from support_service.bot import GREETING, STATUS_UNAVAILABLE
from support_service.models import OrderEvent
from support_service.order_status_consumer import OrderStatusConsumer
from support_service.settings import SupportSettings

from .conftest import API_KEY
from .fakes import FakeOrders, FakeRepository, fake_rabbit
from .harness import BUYER, running_support

# SupportServiceAsyncStub есть только в .pyi, поэтому аннотации с ним — строкой
WAIT_S = 2.0

SERVICE = (("x-api-key", API_KEY),)

ChatCall = grpc.aio.StreamStreamCall[support_pb2.ChatRequest, support_pb2.ChatResponse]


@pytest.fixture
async def stub(
    repository: FakeRepository, orders: FakeOrders
) -> AsyncIterator["support_grpc.SupportServiceAsyncStub"]:
    async with running_support(repository, orders) as stub:
        yield stub


def join(order_id: str) -> support_pb2.ChatRequest:
    return support_pb2.ChatRequest(join=support_pb2.Join(order_id=order_id))


def message(text: str, client_message_id: str = "cm-1") -> support_pb2.ChatRequest:
    return support_pb2.ChatRequest(
        message=support_pb2.ClientMessage(client_message_id=client_message_id, text=text)
    )


async def read(call: ChatCall) -> support_pb2.ChatResponse:
    event = await asyncio.wait_for(call.read(), WAIT_S)
    assert isinstance(event, support_pb2.ChatResponse), event
    return event


async def read_until_end(call: ChatCall) -> list[support_pb2.ChatResponse]:
    events = []
    # read() и async for на одном вызове смешивать нельзя
    while isinstance(
        event := await asyncio.wait_for(call.read(), WAIT_S), support_pb2.ChatResponse
    ):
        events.append(event)
    return events


def kind(event: support_pb2.ChatResponse) -> str | None:
    return event.WhichOneof("payload")


@pytest.mark.usefixtures("fast_agent")
async def test_chat_flow_greeting_bot_and_history(
    stub: "support_grpc.SupportServiceAsyncStub",
) -> None:
    call = stub.Chat(metadata=BUYER)
    await call.write(join("o-1"))
    joined = await read(call)
    # Сервер пишет сам: клиент после join молчит
    typing, greeting = await read(call), await read(call)
    await call.write(message("Где мой заказ?"))
    ack, bot = await read(call), await read(call)
    await call.done_writing()
    tail = await read_until_end(call)
    history = await stub.GetChatHistory(
        support_pb2.GetChatHistoryRequest(order_id="o-1"), metadata=BUYER
    )

    assert kind(joined) == "joined"
    assert kind(typing) == "agent_typing"
    assert (greeting.message.author, greeting.message.text) == (support_pb2.AUTHOR_AGENT, GREETING)
    assert ack.ack.client_message_id == "cm-1"
    assert bot.message.author == support_pb2.AUTHOR_BOT
    assert bot.message.text == "Заказ o-1: передан курьеру"
    assert tail == []
    assert await call.code() is grpc.StatusCode.OK
    trailing = tuple(await call.trailing_metadata())
    assert ("x-close-reason", "client_closed") in trailing
    assert ("x-items-count", "5") in trailing
    assert history.chat_id == joined.joined.chat_id
    assert [m.author for m in history.messages] == [
        support_pb2.AUTHOR_AGENT,
        support_pb2.AUTHOR_CUSTOMER,
        support_pb2.AUTHOR_BOT,
    ]


async def test_idle_closes_ok_with_close_reason(
    short_idle: None, stub: "support_grpc.SupportServiceAsyncStub"
) -> None:
    call = stub.Chat(metadata=BUYER)
    await call.write(join("o-1"))

    events = await read_until_end(call)

    assert [kind(event) for event in events] == ["joined"]
    assert await call.code() is grpc.StatusCode.OK
    assert ("x-close-reason", "idle") in tuple(await call.trailing_metadata())


async def test_unavailable_orders_do_not_break_stream(
    stub: "support_grpc.SupportServiceAsyncStub", orders: FakeOrders
) -> None:
    call = stub.Chat(metadata=BUYER)
    await call.write(join("o-1"))
    await read(call)
    orders.error = DependencyUnavailable("orders")

    await call.write(message("статус?"))
    events = [await read(call), await read(call)]
    await call.write(message("алло", client_message_id="cm-2"))
    after = await read(call)
    call.cancel()

    assert events[1].message.text == STATUS_UNAVAILABLE
    assert after.ack.client_message_id == "cm-2"


async def test_message_before_join_is_failed_precondition(
    stub: "support_grpc.SupportServiceAsyncStub",
) -> None:
    call = stub.Chat(metadata=BUYER)
    await call.write(message("привет"))

    with pytest.raises(grpc.aio.AioRpcError) as info:
        await read(call)

    assert info.value.code() is grpc.StatusCode.FAILED_PRECONDITION
    failure = error_details_pb2.PreconditionFailure()
    assert rich_status(info.value).details[0].Unpack(failure)
    assert failure.violations[0].type == "JOIN_REQUIRED"


async def test_foreign_order_is_not_found(stub: "support_grpc.SupportServiceAsyncStub") -> None:
    call = stub.Chat(metadata=BUYER)
    await call.write(join("o-2"))

    with pytest.raises(grpc.aio.AioRpcError) as info:
        await read(call)

    assert info.value.code() is grpc.StatusCode.NOT_FOUND


async def test_without_token_is_unauthenticated(
    stub: "support_grpc.SupportServiceAsyncStub",
) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stub.GetChatHistory(
            support_pb2.GetChatHistoryRequest(order_id="o-1"), metadata=(("x-api-key", API_KEY),)
        )

    assert info.value.code() is grpc.StatusCode.UNAUTHENTICATED


async def test_history_of_unknown_chat_is_not_found(
    stub: "support_grpc.SupportServiceAsyncStub",
) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stub.GetChatHistory(support_pb2.GetChatHistoryRequest(order_id="o-1"), metadata=BUYER)

    assert info.value.code() is grpc.StatusCode.NOT_FOUND


async def test_order_timeline_by_service_key(
    stub: "support_grpc.SupportServiceAsyncStub", repository: FakeRepository
) -> None:
    changed_at = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
    await repository.record_order_event(OrderEvent("o-1", "PAID", changed_at))

    response = await stub.GetOrderTimeline(
        support_pb2.GetOrderTimelineRequest(order_id="o-1"), metadata=SERVICE
    )

    [event] = response.events
    assert event.status == support_pb2.ORDER_STATUS_PAID
    assert event.changed_at.ToDatetime(tzinfo=UTC) == changed_at


async def test_order_timeline_without_api_key_is_unauthenticated(
    stub: "support_grpc.SupportServiceAsyncStub",
) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stub.GetOrderTimeline(support_pb2.GetOrderTimelineRequest(order_id="o-1"))

    assert info.value.code() is grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.usefixtures("fast_reconnect")
async def test_chat_works_without_broker(
    stub: "support_grpc.SupportServiceAsyncStub", repository: FakeRepository
) -> None:
    """support обслуживает Chat, пока Rabbit.open() бросает, а консьюмер переподключается."""
    rabbit = fake_rabbit(open_errors=1_000)
    consumer = asyncio.create_task(OrderStatusConsumer(rabbit, repository, SupportSettings()).run())
    try:
        call = stub.Chat(metadata=BUYER)
        await call.write(join("o-1"))
        joined = await read(call)
        await call.done_writing()
        await read_until_end(call)

        assert kind(joined) == "joined"
        assert await call.code() is grpc.StatusCode.OK
        assert rabbit.open.await_count >= 1
        assert not consumer.done()
    finally:
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
