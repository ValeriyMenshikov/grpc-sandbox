"""Postgres: пул asyncpg как nuke-di Client."""

import asyncio
from pathlib import Path

import asyncpg
from nuke_di import Client

from stand_core.settings import Settings


class Postgres(Client):
    """Пул соединений asyncpg.

    В `__init__` — только зависимости; пул создаётся в `connect()` и закрывается в `disconnect()`.
    Сервис применяет свой идемпотентный `schema.sql` через `apply_schema` из connect() своего
    репозитория (он зависит от Postgres, поэтому подключается после него).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Postgres is not connected")
        return self._pool

    async def connect(self) -> None:
        dsn = self._settings.postgres_dsn
        if not dsn:
            raise RuntimeError("POSTGRES_DSN is not set")
        self._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)

    async def disconnect(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def apply_schema(self, path: Path) -> None:
        """Выполнить SQL-скрипт целиком (CREATE ... IF NOT EXISTS, сиды с ON CONFLICT)."""
        sql = await asyncio.to_thread(path.read_text, encoding="utf-8")
        await self.pool.execute(sql)
