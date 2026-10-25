"""Чат внутри процесса: сессии открытых стримов Chat и рассылка сообщений чата по ним."""

import asyncio
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import grpc
from nuke_di import Client, client_dataclass
from stand_core.grpc import (
    DependencyUnavailable,
    FailedPrecondition,
    FieldViolation,
    InvalidArgument,
    NotFound,
    PreconditionViolation,
)
from stand_core.logging import get_logger
from support.v1 import support_pb2

from support_service.bot import GREETING, STATUS_UNAVAILABLE, is_status_question, status_reply
from support_service.convert import message_event, message_pb, timestamp
from support_service.models import Author, Chat
from support_service.orders_client import OrdersClient
from support_service.repository import ChatRepository
from support_service.settings import SupportSettings

logger = get_logger(__name__)

# Сколько последних сообщений приходит в joined
LAST_MESSAGES_LIMIT = 20
# Значения trailing metadata x-close-reason
CLOSE_IDLE = "idle"
CLOSE_CLIENT = "client_closed"


@dataclass(frozen=True)
class Close:
    """Стрим завершается OK по причине `reason`."""

    reason: str


Outgoing = support_pb2.ChatResponse | Close | Exception


class ChatSession:
    """Один открытый стрим Chat.

    Чтение входящих, приветствие оператора и ответы бота — отдельные таски; все они пишут в общую
    очередь, а хэндлер отдаёт её клиенту (`events()`). Поэтому сервер пишет, не дожидаясь клиента.
    """

    def __init__(
        self,
        hub: "ChatHub",
        chat: Chat,
        orders: OrdersClient,
        repository: ChatRepository,
        settings: SupportSettings,
    ) -> None:
        self.chat = chat
        self.close_reason: str | None = None
        self._hub = hub
        self._orders = orders
        self._repository = repository
        self._settings = settings
        self._outbox: asyncio.Queue[Outgoing] = asyncio.Queue()
        self._tasks: set[asyncio.Task[None]] = set()
        self._bot_replies: set[asyncio.Task[None]] = set()
        # Сообщения, уже отданные в joined
        self._delivered: set[str] = set()

    async def join(self) -> support_pb2.ChatResponse:
        """joined с последними сообщениями чата; они же потом не придут из очереди повторно."""
        last_messages = await self._repository.last_messages(self.chat.chat_id, LAST_MESSAGES_LIMIT)
        self._delivered.update(message.message_id for message in last_messages)
        return support_pb2.ChatResponse(
            joined=support_pb2.Joined(
                chat_id=self.chat.chat_id,
                last_messages=[message_pb(message) for message in last_messages],
            )
        )

    def send(self, event: support_pb2.ChatResponse) -> None:
        self._outbox.put_nowait(event)

    def start(self, requests: AsyncIterator[support_pb2.ChatRequest]) -> None:
        self._spawn(self._read(requests), "chat.read")
        self._spawn(self._greet(), "chat.greet")

    async def events(self) -> AsyncIterator[support_pb2.ChatResponse]:
        """Исходящие события до `Close`; ошибка любого таска завершает стрим этой ошибкой."""
        while True:
            item = await self._outbox.get()
            if isinstance(item, Close):
                self.close_reason = item.reason
                return
            if isinstance(item, Exception):
                raise item
            if item.HasField("message") and item.message.message_id in self._delivered:
                continue
            yield item

    async def aclose(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _spawn(self, coro: Coroutine[Any, Any, None], name: str) -> asyncio.Task[None]:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def _done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if isinstance(error, Exception):
            self._outbox.put_nowait(error)

    async def _read(self, requests: AsyncIterator[support_pb2.ChatRequest]) -> None:
        while True:
            try:
                async with asyncio.timeout(self._settings.support_idle_timeout_s):
                    request = await anext(requests, None)
            except TimeoutError:
                self._outbox.put_nowait(Close(CLOSE_IDLE))
                return
            if request is None:
                break
            await self._handle(request)
        # Клиент закончил писать: ответы бота на его вопросы дойдут, затем стрим закроется
        await asyncio.gather(*self._bot_replies)
        self._outbox.put_nowait(Close(CLOSE_CLIENT))

    async def _handle(self, request: support_pb2.ChatRequest) -> None:
        match request.WhichOneof("payload"):
            case "message":
                await self._on_message(request.message)
            case "read":
                if not await self._repository.mark_read(self.chat.chat_id, request.read.message_id):
                    logger.info("support.read_unknown", message_id=request.read.message_id)
            case "join":
                raise FailedPrecondition(
                    [
                        PreconditionViolation(
                            "ALREADY_JOINED", f"chat:{self.chat.chat_id}", "join is sent once"
                        )
                    ],
                    message="Already joined",
                )
            case _:
                raise InvalidArgument([FieldViolation("payload", "must be set")])

    async def _on_message(self, message: support_pb2.ClientMessage) -> None:
        if not message.text.strip():
            raise InvalidArgument([FieldViolation("message.text", "must not be empty")])
        saved = await self._repository.add_message(
            self.chat.chat_id, Author.CUSTOMER, message.text, message.client_message_id or None
        )
        self.send(
            support_pb2.ChatResponse(
                ack=support_pb2.Ack(
                    client_message_id=message.client_message_id,
                    message_id=saved.message_id,
                    created_at=timestamp(saved.created_at),
                )
            )
        )
        # Отправитель получил ack; другие стримы этого чата — само сообщение
        self._hub.broadcast(self.chat.chat_id, message_event(saved), exclude=self)
        if is_status_question(message.text):
            task = self._spawn(self._reply_status(), "chat.bot")
            self._bot_replies.add(task)
            task.add_done_callback(self._bot_replies.discard)

    async def _greet(self) -> None:
        await asyncio.sleep(self._settings.support_agent_delay_ms / 1000)
        self.send(support_pb2.ChatResponse(agent_typing=support_pb2.AgentTyping()))
        await self._post(Author.AGENT, GREETING)

    async def _reply_status(self) -> None:
        try:
            order = await self._orders.get_order(self.chat.order_id)
        except (DependencyUnavailable, grpc.aio.AioRpcError) as exc:
            # Недоступный order-service не рвёт чат: бот так и отвечает
            logger.warning(
                "support.order_status_failed", order_id=self.chat.order_id, error=str(exc)
            )
            order = None
        await self._post(Author.BOT, STATUS_UNAVAILABLE if order is None else status_reply(order))

    async def _post(self, author: Author, text: str) -> None:
        saved = await self._repository.add_message(self.chat.chat_id, author, text)
        self._hub.broadcast(self.chat.chat_id, message_event(saved))


@client_dataclass
class ChatHub(Client):
    """Открытые стримы по чатам: сообщение чата получают все его стримы в этом процессе."""

    _repository: ChatRepository
    _settings: SupportSettings
    _sessions: dict[str, set[ChatSession]] = field(default_factory=dict, init=False)

    @asynccontextmanager
    async def session(
        self, order_id: str, user_id: str, orders: OrdersClient
    ) -> AsyncIterator[ChatSession]:
        """Сессия стрима в чате заказа (чат создаётся при первом join); владелец уже проверен.

        Сессия получает сообщения чата сразу, ещё до joined: ничего не теряется между чтением
        последних сообщений и стартом сессии.
        """
        chat = await self._repository.get_or_create_chat(order_id, user_id)
        if chat.user_id != user_id:
            raise NotFound("order", order_id)
        session = ChatSession(self, chat, orders, self._repository, self._settings)
        sessions = self._sessions.setdefault(chat.chat_id, set())
        sessions.add(session)
        try:
            yield session
        finally:
            sessions.discard(session)
            if not sessions:
                self._sessions.pop(chat.chat_id, None)
            await session.aclose()

    def broadcast(
        self,
        chat_id: str,
        event: support_pb2.ChatResponse,
        exclude: ChatSession | None = None,
    ) -> None:
        for session in self._sessions.get(chat_id, ()):
            if session is not exclude:
                session.send(event)
