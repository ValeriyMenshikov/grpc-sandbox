"""SQL репозитория против Postgres из compose (make up) во временной базе.

Без доступного Postgres тесты пропускаются: unit-тесты хэндлеров обходятся без него.
Адрес — env TEST_POSTGRES_DSN, по умолчанию Postgres из compose на localhost.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from stand_core.clients import Postgres
from support_service.models import Author, OrderEvent
from support_service.repository import ChatRepository
from support_service.settings import SupportSettings

ADMIN_DSN = os.environ.get("TEST_POSTGRES_DSN", "postgresql://stand:stand@localhost:5432/stand")


@pytest.fixture
async def postgres(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Postgres]:
    try:
        admin = await asyncpg.connect(ADMIN_DSN, timeout=2)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres is not available ({exc}); run make up")
    database = f"support_test_{uuid.uuid4().hex[:12]}"
    await admin.execute(f'CREATE DATABASE "{database}"')
    monkeypatch.setenv("POSTGRES_DSN", f"{ADMIN_DSN.rsplit('/', 1)[0]}/{database}")
    client = Postgres(SupportSettings())
    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.close()


@pytest.fixture
async def repository(postgres: Postgres) -> ChatRepository:
    repository = ChatRepository(postgres)
    await repository.connect()
    # Схема идемпотентна: второй connect() не падает
    await repository.connect()
    return repository


async def test_one_chat_per_order(repository: ChatRepository) -> None:
    created = await repository.get_or_create_chat("o-1", "u1")
    again = await repository.get_or_create_chat("o-1", "u1")
    other = await repository.get_or_create_chat("o-2", "u1")

    assert again == created
    assert other.chat_id != created.chat_id
    assert await repository.find_chat("o-1") == created
    assert await repository.find_chat("missing") is None


async def test_messages_keep_send_order(repository: ChatRepository) -> None:
    chat = await repository.get_or_create_chat("o-1", "u1")
    texts = [f"m{index}" for index in range(5)]
    saved = [await repository.add_message(chat.chat_id, Author.CUSTOMER, text) for text in texts]
    await repository.add_message(chat.chat_id, Author.BOT, "ответ")

    last = await repository.last_messages(chat.chat_id, 3)
    page = await repository.list_messages(chat.chat_id, 1, 2)

    assert saved[0].author is Author.CUSTOMER
    assert [m.text for m in last] == ["m3", "m4", "ответ"]
    assert last[-1].author is Author.BOT
    assert [m.text for m in page] == ["m1", "m2"]
    assert await repository.list_messages(chat.chat_id, 10, 5) == []


async def test_client_message_id_and_read(repository: ChatRepository, postgres: Postgres) -> None:
    chat = await repository.get_or_create_chat("o-1", "u1")
    other = await repository.get_or_create_chat("o-2", "u1")
    message = await repository.add_message(chat.chat_id, Author.CUSTOMER, "привет", "cm-1")

    assert await repository.mark_read(chat.chat_id, message.message_id)
    # Повторное прочтение не сдвигает read_at; чужой чат и неизвестное сообщение — False
    first_read = await postgres.pool.fetchval(
        "SELECT read_at FROM support.messages WHERE message_id = $1", message.message_id
    )
    assert await repository.mark_read(chat.chat_id, message.message_id)
    assert not await repository.mark_read(other.chat_id, message.message_id)
    assert not await repository.mark_read(chat.chat_id, "missing")
    row = await postgres.pool.fetchrow(
        "SELECT client_message_id, read_at FROM support.messages WHERE message_id = $1",
        message.message_id,
    )
    assert row is not None
    assert row["client_message_id"] == "cm-1"
    assert row["read_at"] == first_read is not None


def moment(minutes: int = 0) -> datetime:
    return datetime(2026, 10, 26, 12, 0, tzinfo=UTC) + timedelta(minutes=minutes)


async def test_projection_is_idempotent(repository: ChatRepository) -> None:
    event = OrderEvent(order_id="o-1", status="PAID", changed_at=moment())

    await repository.record_order_event(event)
    await repository.record_order_event(event)

    assert await repository.order_events("o-1") == [event]


async def test_projection_is_ordered_by_changed_at(repository: ChatRepository) -> None:
    created = OrderEvent("o-1", "CREATED", moment(0))
    paid = OrderEvent("o-1", "PAID", moment(1))
    other = OrderEvent("o-2", "CREATED", moment(0))
    # Очередь не гарантирует порядок между перезапусками: более позднее событие пришло первым
    for event in (paid, other, created):
        await repository.record_order_event(event)

    assert await repository.order_events("o-1") == [created, paid]
    assert await repository.order_events("missing") == []
