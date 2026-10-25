"""SQL репозитория против Postgres из compose (make up) во временной базе.

Без доступного Postgres тесты пропускаются: unit-тесты хэндлеров обходятся без него.
Адрес — env TEST_POSTGRES_DSN, по умолчанию Postgres из compose на localhost.
"""

import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
from notification_service.models import NotificationStatus
from notification_service.repository import NotificationRepository
from notification_service.settings import NotificationSettings
from stand_core.clients import Postgres

ADMIN_DSN = os.environ.get("TEST_POSTGRES_DSN", "postgresql://stand:stand@localhost:5432/stand")


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAND_API_KEY", "test-key")


@pytest.fixture
async def postgres(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Postgres]:
    try:
        admin = await asyncpg.connect(ADMIN_DSN, timeout=2)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres is not available ({exc}); run make up")
    database = f"notifications_test_{uuid.uuid4().hex[:12]}"
    await admin.execute(f'CREATE DATABASE "{database}"')
    monkeypatch.setenv("POSTGRES_DSN", f"{ADMIN_DSN.rsplit('/', 1)[0]}/{database}")
    client = Postgres(NotificationSettings())
    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.close()


@pytest.fixture
async def repository(postgres: Postgres) -> NotificationRepository:
    repository = NotificationRepository(postgres)
    await repository.connect()
    # Схема идемпотентна: второй connect() не падает
    await repository.connect()
    return repository


async def test_record_returns_stored_notification(repository: NotificationRepository) -> None:
    sent = await repository.record("a@example.com", "Код", NotificationStatus.SENT)
    failed = await repository.record("", "", NotificationStatus.FAILED, "bad event")

    assert uuid.UUID(sent.notification_id)
    assert (sent.to_email, sent.subject, sent.status, sent.error) == (
        "a@example.com",
        "Код",
        NotificationStatus.SENT,
        "",
    )
    assert (failed.status, failed.error) == (NotificationStatus.FAILED, "bad event")
    assert sent.notification_id != failed.notification_id


async def test_list_newest_first_with_offset(repository: NotificationRepository) -> None:
    ids = [
        (await repository.record(f"u{i}@example.com", "s", NotificationStatus.SENT)).notification_id
        for i in range(3)
    ]

    everything = await repository.list_notifications(None, 0, 10)
    page = await repository.list_notifications(None, 1, 1)

    assert [n.notification_id for n in everything] == ids[::-1]
    assert [n.notification_id for n in page] == [ids[1]]
    assert await repository.list_notifications(None, 3, 10) == []


async def test_list_filters_by_email_case_insensitive(
    repository: NotificationRepository,
) -> None:
    mine = await repository.record("Buyer@Example.com", "s", NotificationStatus.SENT)
    await repository.record("other@example.com", "s", NotificationStatus.SENT)

    found = await repository.list_notifications("buyer@example.COM", 0, 10)

    assert [n.notification_id for n in found] == [mine.notification_id]
