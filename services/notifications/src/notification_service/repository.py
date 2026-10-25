"""Журнал писем поверх Postgres (схема `notifications`, см. schema.sql)."""

import uuid
from pathlib import Path

import asyncpg
from nuke_di import Client, client_dataclass
from stand_core.clients import Postgres

from notification_service.models import Notification, NotificationStatus

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_COLUMNS = "notification_id::text, to_email, subject, status, error, created_at"

_INSERT = f"""
INSERT INTO notifications.sent_emails (notification_id, to_email, subject, status, error)
VALUES ($1, $2, $3, $4, $5)
RETURNING {_COLUMNS}
"""

# Фильтр без учёта регистра — под индекс по lower(to_email)
_LIST = f"""
SELECT {_COLUMNS} FROM notifications.sent_emails
WHERE ($1::text IS NULL OR lower(to_email) = lower($1))
ORDER BY created_at DESC, notification_id DESC
OFFSET $2 LIMIT $3
"""


def _notification(record: asyncpg.Record) -> Notification:
    return Notification(
        notification_id=record["notification_id"],
        to_email=record["to_email"],
        subject=record["subject"],
        status=NotificationStatus(record["status"]),
        error=record["error"],
        created_at=record["created_at"],
    )


@client_dataclass
class NotificationRepository(Client):
    _postgres: Postgres

    async def connect(self) -> None:
        await self._postgres.apply_schema(SCHEMA_PATH)

    async def record(
        self, to_email: str, subject: str, status: NotificationStatus, error: str = ""
    ) -> Notification:
        """Записать попытку отправки; notification_id выбирает репозиторий."""
        record = await self._postgres.pool.fetchrow(
            _INSERT, uuid.uuid4(), to_email, subject, status.value, error
        )
        assert record is not None
        return _notification(record)

    async def list_notifications(
        self, to_email: str | None, offset: int, limit: int
    ) -> list[Notification]:
        """Попытки отправки, новые первыми; `to_email` None — все адресаты."""
        records = await self._postgres.pool.fetch(_LIST, to_email, offset, limit)
        return [_notification(record) for record in records]
