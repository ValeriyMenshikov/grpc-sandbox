"""Репозиторий, клиент к order-service, стрим Chat и сообщения RabbitMQ в памяти для unit-тестов."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import TracebackType
from unittest.mock import AsyncMock, MagicMock

from orders.v1 import orders_pb2
from stand_core.grpc import current_user
from support.v1 import support_pb2
from support_service.models import Author, Chat, ChatMessage, OrderEvent
from support_service.orders_client import OrdersClient
from support_service.repository import ChatRepository

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
BUYER_ID = "u-buyer"
OTHER_ID = "u-other"


def order(
    order_id: str,
    user_id: str = BUYER_ID,
    status: orders_pb2.OrderStatus.ValueType = orders_pb2.ORDER_STATUS_HANDED_TO_COURIER,
) -> orders_pb2.Order:
    return orders_pb2.Order(order_id=order_id, user_id=user_id, status=status)


class FakeRepository(ChatRepository):
    def __init__(self) -> None:
        self.chats: dict[str, Chat] = {}
        self.messages: list[ChatMessage] = []
        self.client_ids: dict[str, str | None] = {}
        self.read: set[str] = set()
        self.events: dict[str, list[OrderEvent]] = {}
        # Исключение, которое бросит следующая запись проекции (например, Postgres недоступен)
        self.event_error: Exception | None = None
        self._clock = EPOCH

    async def connect(self) -> None:
        pass

    async def get_or_create_chat(self, order_id: str, user_id: str) -> Chat:
        if order_id not in self.chats:
            self.chats[order_id] = Chat(f"c-{len(self.chats) + 1}", order_id, user_id)
        return self.chats[order_id]

    async def find_chat(self, order_id: str) -> Chat | None:
        return self.chats.get(order_id)

    async def add_message(
        self, chat_id: str, author: Author, text: str, client_message_id: str | None = None
    ) -> ChatMessage:
        self._clock += timedelta(seconds=1)
        message = ChatMessage(f"m-{len(self.messages) + 1}", chat_id, author, text, self._clock)
        self.messages.append(message)
        self.client_ids[message.message_id] = client_message_id
        return message

    def of(self, chat_id: str) -> list[ChatMessage]:
        return [message for message in self.messages if message.chat_id == chat_id]

    async def last_messages(self, chat_id: str, limit: int) -> list[ChatMessage]:
        return self.of(chat_id)[-limit:]

    async def list_messages(self, chat_id: str, offset: int, limit: int) -> list[ChatMessage]:
        return self.of(chat_id)[offset : offset + limit]

    async def mark_read(self, chat_id: str, message_id: str) -> bool:
        if not any(m.message_id == message_id for m in self.of(chat_id)):
            return False
        self.read.add(message_id)
        return True

    async def record_order_event(self, event: OrderEvent) -> None:
        if self.event_error is not None:
            raise self.event_error
        events = self.events.setdefault(event.order_id, [])
        if all(known.status != event.status for known in events):
            events.append(event)

    async def order_events(self, order_id: str) -> list[OrderEvent]:
        return sorted(self.events.get(order_id, []), key=lambda event: event.changed_at)


class FakeOrders(OrdersClient):
    """OrderService в памяти: как настоящий, чужой заказ не отдаёт."""

    def __init__(self, orders: Iterable[orders_pb2.Order] = ()) -> None:
        self.orders = {item.order_id: item for item in orders}
        self.calls: list[str] = []
        # Исключение, которое бросит следующий вызов (например, DependencyUnavailable)
        self.error: Exception | None = None

    async def get_order(self, order_id: str) -> orders_pb2.Order | None:
        self.calls.append(order_id)
        if self.error is not None:
            raise self.error
        found = self.orders.get(order_id)
        if found is None or found.user_id != current_user().id:
            return None
        return found


@dataclass
class RequestStream:
    """Входящий стрим Chat: тест пишет в него, когда хочет; `close()` — клиент закончил писать."""

    queue: "asyncio.Queue[support_pb2.ChatRequest | None]"

    @classmethod
    def new(cls) -> "RequestStream":
        return cls(asyncio.Queue())

    def join(self, order_id: str) -> None:
        self.queue.put_nowait(support_pb2.ChatRequest(join=support_pb2.Join(order_id=order_id)))

    def message(self, text: str, client_message_id: str = "cm-1") -> None:
        self.queue.put_nowait(
            support_pb2.ChatRequest(
                message=support_pb2.ClientMessage(client_message_id=client_message_id, text=text)
            )
        )

    def read(self, message_id: str) -> None:
        self.queue.put_nowait(support_pb2.ChatRequest(read=support_pb2.Read(message_id=message_id)))

    def close(self) -> None:
        self.queue.put_nowait(None)

    def __aiter__(self) -> "RequestStream":
        return self

    async def __anext__(self) -> support_pb2.ChatRequest:
        item = await self.queue.get()
        if item is None:
            raise StopAsyncIteration
        return item


def rabbit_message(body: bytes, correlation_id: str | None = "req-from-header") -> MagicMock:
    """Входящее сообщение aio-pika: тело, заголовки и ack/nack."""
    incoming = MagicMock()
    incoming.body = body
    incoming.message_id = uuid.uuid4().hex
    incoming.correlation_id = correlation_id
    incoming.ack = AsyncMock()
    incoming.nack = AsyncMock()
    return incoming


class FakeQueueIterator:
    """`queue.iterator()`: асинхронный контекст и итератор по заранее заданным сообщениям."""

    def __init__(self, messages: list[MagicMock]) -> None:
        self.messages = messages

    async def __aenter__(self) -> AsyncIterator[MagicMock]:
        return self._iterate()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        pass

    async def _iterate(self) -> AsyncIterator[MagicMock]:
        for incoming in self.messages:
            yield incoming


def fake_rabbit(*messages: MagicMock, open_errors: int = 0) -> MagicMock:
    """Rabbit: первые `open_errors` вызовов `open()` падают, потом очередь отдаёт `messages`."""
    queue = MagicMock()
    queue.name = "support.order_events"
    queue.bind = AsyncMock()
    queue.iterator.side_effect = lambda: FakeQueueIterator(list(messages))
    channel = MagicMock()
    channel.set_qos = AsyncMock()
    channel.declare_exchange = AsyncMock()
    channel.declare_queue = AsyncMock(return_value=queue)
    rabbit = MagicMock()
    rabbit.channel = channel
    attempts = iter(range(open_errors))

    async def open_() -> None:
        if next(attempts, None) is not None:
            raise ConnectionError("broker is down")

    rabbit.open = AsyncMock(side_effect=open_)
    rabbit.disconnect = AsyncMock()
    rabbit.queue = queue
    return rabbit
