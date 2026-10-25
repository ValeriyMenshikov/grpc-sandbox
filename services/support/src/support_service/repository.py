"""Репозиторий чатов поддержки поверх Postgres (схема `support`, см. schema.sql)."""

import uuid
from pathlib import Path

import asyncpg
from nuke_di import Client, client_dataclass
from stand_core.clients import Postgres

from support_service.models import Author, Chat, ChatMessage

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_CHAT_COLUMNS = "chat_id, order_id, user_id"
_MESSAGE_COLUMNS = "message_id, chat_id, author, text, created_at"

# DO UPDATE без изменений — чтобы RETURNING вернул и уже существующий чат
_UPSERT_CHAT = f"""
INSERT INTO support.chats (chat_id, order_id, user_id)
VALUES ($1, $2, $3)
ON CONFLICT (order_id) DO UPDATE SET order_id = EXCLUDED.order_id
RETURNING {_CHAT_COLUMNS}
"""

_INSERT_MESSAGE = f"""
INSERT INTO support.messages (message_id, chat_id, author, text, client_message_id)
VALUES ($1, $2, $3, $4, $5)
RETURNING {_MESSAGE_COLUMNS}
"""

# Последние `limit` сообщений, старые первыми
_LAST_MESSAGES = f"""
SELECT {_MESSAGE_COLUMNS} FROM (
    SELECT {_MESSAGE_COLUMNS}, seq FROM support.messages
    WHERE chat_id = $1 ORDER BY seq DESC LIMIT $2
) AS last ORDER BY seq
"""


def _chat(record: asyncpg.Record) -> Chat:
    return Chat(chat_id=record["chat_id"], order_id=record["order_id"], user_id=record["user_id"])


def _message(record: asyncpg.Record) -> ChatMessage:
    return ChatMessage(
        message_id=record["message_id"],
        chat_id=record["chat_id"],
        author=Author(record["author"]),
        text=record["text"],
        created_at=record["created_at"],
    )


@client_dataclass
class ChatRepository(Client):
    _postgres: Postgres

    async def connect(self) -> None:
        await self._postgres.apply_schema(SCHEMA_PATH)

    async def get_or_create_chat(self, order_id: str, user_id: str) -> Chat:
        """Чат заказа; нет — создаётся. Владелец заказа уже проверен вызывающим."""
        record = await self._postgres.pool.fetchrow(
            _UPSERT_CHAT, str(uuid.uuid4()), order_id, user_id
        )
        assert record is not None
        return _chat(record)

    async def find_chat(self, order_id: str) -> Chat | None:
        record = await self._postgres.pool.fetchrow(
            f"SELECT {_CHAT_COLUMNS} FROM support.chats WHERE order_id = $1", order_id
        )
        return None if record is None else _chat(record)

    async def add_message(
        self, chat_id: str, author: Author, text: str, client_message_id: str | None = None
    ) -> ChatMessage:
        record = await self._postgres.pool.fetchrow(
            _INSERT_MESSAGE, str(uuid.uuid4()), chat_id, author.value, text, client_message_id
        )
        assert record is not None
        return _message(record)

    async def last_messages(self, chat_id: str, limit: int) -> list[ChatMessage]:
        """Последние `limit` сообщений чата, старые первыми."""
        records = await self._postgres.pool.fetch(_LAST_MESSAGES, chat_id, limit)
        return [_message(record) for record in records]

    async def list_messages(self, chat_id: str, offset: int, limit: int) -> list[ChatMessage]:
        """Страница истории чата, старые первыми."""
        records = await self._postgres.pool.fetch(
            f"SELECT {_MESSAGE_COLUMNS} FROM support.messages "
            "WHERE chat_id = $1 ORDER BY seq OFFSET $2 LIMIT $3",
            chat_id,
            offset,
            limit,
        )
        return [_message(record) for record in records]

    async def mark_read(self, chat_id: str, message_id: str) -> bool:
        """Отметить сообщение чата прочитанным; False — такого сообщения в чате нет."""
        result = await self._postgres.pool.execute(
            "UPDATE support.messages SET read_at = coalesce(read_at, now()) "
            "WHERE chat_id = $1 AND message_id = $2",
            chat_id,
            message_id,
        )
        return result != "UPDATE 0"
