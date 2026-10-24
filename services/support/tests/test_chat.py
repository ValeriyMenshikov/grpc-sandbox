"""Chat напрямую: join первым, ack, приветствие без запроса клиента, бот, idle, закрытие."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from typing import cast
from unittest.mock import Mock, call

import pytest
from stand_core.grpc import DependencyUnavailable, FailedPrecondition, InvalidArgument, NotFound
from support.v1 import support_pb2
from support_service.bot import GREETING, STATUS_UNAVAILABLE
from support_service.chat_hub import ChatHub
from support_service.handlers.chat_s_s import chat
from support_service.models import Author
from support_service.settings import SupportSettings

from .fakes import FakeOrders, FakeRepository, RequestStream

pytestmark = pytest.mark.usefixtures("buyer")

# Сколько ждать события, которое должно прийти
WAIT_S = 2.0

Stream = AsyncGenerator[support_pb2.ChatResponse]


def open_chat(
    requests: RequestStream,
    context: Mock,
    hub: ChatHub,
    orders: FakeOrders,
    settings: SupportSettings,
) -> Stream:
    # Хэндлер — async-генератор: тесту нужен его aclose()
    return cast(Stream, chat(requests, context, hub, orders, settings))


async def next_event(stream: Stream) -> support_pb2.ChatResponse:
    return await asyncio.wait_for(anext(stream), WAIT_S)


async def rest(stream: Stream) -> list[support_pb2.ChatResponse]:
    async with asyncio.timeout(WAIT_S):
        return [event async for event in stream]


def kind(event: support_pb2.ChatResponse) -> str | None:
    return event.WhichOneof("payload")


@pytest.fixture
def requests() -> RequestStream:
    return RequestStream.new()


@pytest.fixture
async def joined(
    requests: RequestStream,
    context: Mock,
    hub: ChatHub,
    orders: FakeOrders,
    settings: SupportSettings,
) -> AsyncIterator[Stream]:
    """Стрим после join к заказу o-1 и полученного joined."""
    stream = open_chat(requests, context, hub, orders, settings)
    requests.join("o-1")
    assert kind(await next_event(stream)) == "joined"
    yield stream
    await stream.aclose()


async def test_join_must_be_first(
    requests: RequestStream,
    context: Mock,
    hub: ChatHub,
    orders: FakeOrders,
    settings: SupportSettings,
) -> None:
    requests.message("привет")

    with pytest.raises(FailedPrecondition) as info:
        await next_event(open_chat(requests, context, hub, orders, settings))

    assert info.value.violations[0].type == "JOIN_REQUIRED"
    assert orders.calls == []


async def test_stream_closed_before_join_is_failed_precondition(
    requests: RequestStream,
    context: Mock,
    hub: ChatHub,
    orders: FakeOrders,
    settings: SupportSettings,
) -> None:
    requests.close()

    with pytest.raises(FailedPrecondition):
        await next_event(open_chat(requests, context, hub, orders, settings))


async def test_empty_order_id_is_invalid_argument(
    requests: RequestStream,
    context: Mock,
    hub: ChatHub,
    orders: FakeOrders,
    settings: SupportSettings,
) -> None:
    requests.join("")

    with pytest.raises(InvalidArgument):
        await next_event(open_chat(requests, context, hub, orders, settings))


@pytest.mark.parametrize("order_id", ["o-2", "missing"])
async def test_foreign_or_missing_order_is_not_found(
    requests: RequestStream,
    context: Mock,
    hub: ChatHub,
    orders: FakeOrders,
    settings: SupportSettings,
    repository: FakeRepository,
    order_id: str,
) -> None:
    requests.join(order_id)

    with pytest.raises(NotFound):
        await next_event(open_chat(requests, context, hub, orders, settings))

    assert orders.calls == [order_id]
    assert repository.chats == {}


async def test_orders_unavailable_on_join_is_unavailable(
    requests: RequestStream,
    context: Mock,
    hub: ChatHub,
    orders: FakeOrders,
    settings: SupportSettings,
) -> None:
    orders.error = DependencyUnavailable("orders")
    requests.join("o-1")

    with pytest.raises(DependencyUnavailable):
        await next_event(open_chat(requests, context, hub, orders, settings))


async def test_joined_has_last_messages_oldest_first(
    requests: RequestStream,
    context: Mock,
    hub: ChatHub,
    orders: FakeOrders,
    settings: SupportSettings,
    repository: FakeRepository,
) -> None:
    existing = await repository.get_or_create_chat("o-1", "u-buyer")
    for text in ("первое", "второе"):
        await repository.add_message(existing.chat_id, Author.CUSTOMER, text)
    requests.join("o-1")
    stream = open_chat(requests, context, hub, orders, settings)

    event = await next_event(stream)
    await stream.aclose()

    assert event.joined.chat_id == existing.chat_id
    assert [m.text for m in event.joined.last_messages] == ["первое", "второе"]
    assert event.joined.last_messages[0].author == support_pb2.AUTHOR_CUSTOMER


async def test_agent_greets_without_client_request(
    requests: RequestStream,
    context: Mock,
    hub: ChatHub,
    orders: FakeOrders,
    repository: FakeRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPPORT_AGENT_DELAY_MS", "20")
    settings = SupportSettings()
    stream = open_chat(requests, context, ChatHub(repository, settings), orders, settings)
    requests.join("o-1")

    # Клиент после join ничего не пишет, а сервер пишет сам
    events = [await next_event(stream) for _ in range(3)]
    await stream.aclose()

    assert [kind(event) for event in events] == ["joined", "agent_typing", "message"]
    assert events[2].message.author == support_pb2.AUTHOR_AGENT
    assert events[2].message.text == GREETING
    assert [(m.author, m.text) for m in repository.messages] == [(Author.AGENT, GREETING)]


async def test_message_is_acked_and_saved(
    joined: Stream, requests: RequestStream, repository: FakeRepository
) -> None:
    requests.message("Здравствуйте", client_message_id="cm-7")

    event = await next_event(joined)

    assert kind(event) == "ack"
    assert event.ack.client_message_id == "cm-7"
    saved = repository.messages[0]
    assert (saved.author, saved.text) == (Author.CUSTOMER, "Здравствуйте")
    assert event.ack.message_id == saved.message_id
    assert event.ack.created_at.seconds == int(saved.created_at.timestamp())
    assert repository.client_ids[saved.message_id] == "cm-7"


async def test_bot_answers_status_question(
    joined: Stream, requests: RequestStream, repository: FakeRepository, orders: FakeOrders
) -> None:
    requests.message("Где мой заказ?")

    events = [await next_event(joined) for _ in range(2)]

    assert [kind(event) for event in events] == ["ack", "message"]
    assert events[1].message.author == support_pb2.AUTHOR_BOT
    assert events[1].message.text == "Заказ o-1: передан курьеру"
    assert orders.calls == ["o-1", "o-1"]
    assert [m.author for m in repository.messages] == [Author.CUSTOMER, Author.BOT]


async def test_plain_message_gets_no_bot_reply(
    joined: Stream, requests: RequestStream, orders: FakeOrders
) -> None:
    requests.message("спасибо")
    requests.message("до свидания", client_message_id="cm-2")
    requests.close()

    events = [await next_event(joined), *await rest(joined)]

    assert [kind(event) for event in events] == ["ack", "ack"]
    assert orders.calls == ["o-1"]


async def test_unavailable_orders_do_not_break_chat(
    joined: Stream, requests: RequestStream, orders: FakeOrders
) -> None:
    orders.error = DependencyUnavailable("orders")
    requests.message("какой статус?")

    events = [await next_event(joined) for _ in range(2)]
    requests.message("ещё тут", client_message_id="cm-2")
    after = await next_event(joined)

    assert events[1].message.author == support_pb2.AUTHOR_BOT
    assert events[1].message.text == STATUS_UNAVAILABLE
    assert kind(after) == "ack"
    assert after.ack.client_message_id == "cm-2"


async def test_idle_closes_ok_with_close_reason(
    requests: RequestStream,
    context: Mock,
    orders: FakeOrders,
    repository: FakeRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPPORT_IDLE_TIMEOUT_S", "0.1")
    settings = SupportSettings()
    stream = open_chat(requests, context, ChatHub(repository, settings), orders, settings)
    requests.join("o-1")
    requests.message("привет")

    events = await rest(stream)

    assert [kind(event) for event in events] == ["joined", "ack"]
    context.set_trailing_metadata.assert_called_once_with((("x-close-reason", "idle"),))


async def test_idle_before_join_closes_ok(
    requests: RequestStream,
    context: Mock,
    orders: FakeOrders,
    repository: FakeRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPPORT_IDLE_TIMEOUT_S", "0.05")
    settings = SupportSettings()

    events = await rest(
        open_chat(requests, context, ChatHub(repository, settings), orders, settings)
    )

    assert events == []
    assert context.set_trailing_metadata.call_args == call((("x-close-reason", "idle"),))
    assert orders.calls == []


async def test_client_close_waits_for_bot_reply(
    joined: Stream, requests: RequestStream, context: Mock
) -> None:
    requests.message("статус заказа")
    requests.close()

    events = await rest(joined)

    assert [kind(event) for event in events] == ["ack", "message"]
    context.set_trailing_metadata.assert_called_once_with((("x-close-reason", "client_closed"),))


async def test_read_marks_message(
    joined: Stream, requests: RequestStream, repository: FakeRepository
) -> None:
    requests.message("привет")
    ack = await next_event(joined)

    requests.read(ack.ack.message_id)
    requests.read("unknown")
    requests.close()
    await rest(joined)

    assert repository.read == {ack.ack.message_id}


async def test_second_join_is_failed_precondition(joined: Stream, requests: RequestStream) -> None:
    requests.join("o-1")

    with pytest.raises(FailedPrecondition) as info:
        await next_event(joined)

    assert info.value.violations[0].type == "ALREADY_JOINED"


async def test_empty_text_is_invalid_argument(joined: Stream, requests: RequestStream) -> None:
    requests.message("   ")

    with pytest.raises(InvalidArgument):
        await next_event(joined)


async def test_messages_reach_other_streams_of_the_chat(
    joined: Stream,
    requests: RequestStream,
    context: Mock,
    hub: ChatHub,
    orders: FakeOrders,
    settings: SupportSettings,
) -> None:
    other_requests = RequestStream.new()
    other = open_chat(other_requests, context, hub, orders, settings)
    other_requests.join("o-1")
    assert kind(await next_event(other)) == "joined"

    requests.message("где заказ?")
    own = [await next_event(joined) for _ in range(2)]
    seen = [await next_event(other) for _ in range(2)]
    await other.aclose()

    assert [kind(event) for event in own] == ["ack", "message"]
    # Второй стрим получает и сообщение покупателя, и ответ бота
    assert [event.message.author for event in seen] == [
        support_pb2.AUTHOR_CUSTOMER,
        support_pb2.AUTHOR_BOT,
    ]
    assert seen[0].message.message_id == own[0].ack.message_id


async def test_closed_stream_leaves_hub(
    requests: RequestStream,
    context: Mock,
    hub: ChatHub,
    orders: FakeOrders,
    settings: SupportSettings,
) -> None:
    stream = open_chat(requests, context, hub, orders, settings)
    requests.join("o-1")
    requests.close()

    await rest(stream)

    assert hub._sessions == {}


async def test_cancelled_stream_leaves_hub(
    requests: RequestStream,
    context: Mock,
    hub: ChatHub,
    orders: FakeOrders,
    settings: SupportSettings,
) -> None:
    stream = open_chat(requests, context, hub, orders, settings)
    requests.join("o-1")
    assert kind(await next_event(stream)) == "joined"

    # Клиент оборвал стрим без half-close
    await stream.aclose()

    assert hub._sessions == {}


async def test_message_in_joined_is_not_repeated_from_queue(
    hub: ChatHub, orders: FakeOrders, repository: FakeRepository
) -> None:
    async with hub.session("o-1", "u-buyer", orders) as session:
        # Сообщение пришло в чат между регистрацией сессии и чтением последних сообщений
        await session._post(Author.AGENT, "уже в joined")
        joined = await session.join()
        await session._post(Author.AGENT, "новое")
        event = await asyncio.wait_for(anext(session.events()), WAIT_S)

    assert [m.text for m in joined.joined.last_messages] == ["уже в joined"]
    assert event.message.text == "новое"
