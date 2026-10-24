"""Репозиторий пользователей поверх Postgres (схема `users`, см. schema.sql)."""

from collections.abc import Mapping
from pathlib import Path

import asyncpg
from nuke_di import Client
from stand_core.clients import Postgres
from stand_core.grpc import Role

from user_service.models import ProfileField, User, UserStatus
from user_service.passwords import hash_password_async
from user_service.settings import UserSettings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Продавец-сид: id совпадает с seller_id товаров-сидов catalog-service (docs/decisions.md)
SEED_SELLER_ID = "00000000-0000-4000-8000-000000000001"
SEED_SELLER_EMAIL = "seller@stand.local"
SEED_SELLER_NAME = "Продавец стенда"

_USER_COLUMNS = (
    "user_id, email, display_name, phone, role, status, password_hash, created_at, updated_at"
)

# ON CONFLICT DO NOTHING: перезапуск не затирает правки курса (смену пароля, профиль)
_SEED_SELLER = """
INSERT INTO users.users (user_id, email, password_hash, display_name, role, status)
VALUES ($1, $2, $3, $4, 'SELLER', 'ACTIVE')
ON CONFLICT DO NOTHING
"""

_CREATE_USER = f"""
INSERT INTO users.users (email, password_hash, display_name, role, status)
VALUES ($1, $2, $3, $4, 'PENDING')
ON CONFLICT (email) DO NOTHING
RETURNING {_USER_COLUMNS}
"""

_ACTIVATE = f"""
UPDATE users.users SET status = 'ACTIVE', updated_at = now()
WHERE user_id = $1
RETURNING {_USER_COLUMNS}
"""

_SET_PASSWORD = """
UPDATE users.users SET password_hash = $2, updated_at = now() WHERE email = $1
"""


def _user(record: asyncpg.Record) -> User:
    return User(
        user_id=record["user_id"],
        email=record["email"],
        display_name=record["display_name"],
        phone=record["phone"],
        role=Role(record["role"]),
        status=UserStatus(record["status"]),
        password_hash=record["password_hash"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


class UserRepository(Client):
    def __init__(self, postgres: Postgres, settings: UserSettings) -> None:
        self._postgres = postgres
        self._settings = settings

    async def connect(self) -> None:
        await self._postgres.apply_schema(SCHEMA_PATH)
        await self._seed()

    async def _seed(self) -> None:
        exists = await self._postgres.pool.fetchval(
            "SELECT true FROM users.users WHERE user_id = $1", SEED_SELLER_ID
        )
        if exists:
            # Не считаем scrypt на каждом старте: сид уже есть
            return
        password_hash = await hash_password_async(self._settings.seed_seller_password)
        await self._postgres.pool.execute(
            _SEED_SELLER, SEED_SELLER_ID, SEED_SELLER_EMAIL, password_hash, SEED_SELLER_NAME
        )

    async def create_user(
        self, email: str, password_hash: str, display_name: str, role: Role
    ) -> User | None:
        """Новый пользователь в статусе PENDING; None — email уже занят."""
        record = await self._postgres.pool.fetchrow(
            _CREATE_USER, email, password_hash, display_name, role.value
        )
        return None if record is None else _user(record)

    async def get_by_email(self, email: str) -> User | None:
        record = await self._postgres.pool.fetchrow(
            f"SELECT {_USER_COLUMNS} FROM users.users WHERE email = $1", email
        )
        return None if record is None else _user(record)

    async def get_by_id(self, user_id: str) -> User | None:
        record = await self._postgres.pool.fetchrow(
            f"SELECT {_USER_COLUMNS} FROM users.users WHERE user_id = $1", user_id
        )
        return None if record is None else _user(record)

    async def activate(self, user_id: str) -> User | None:
        record = await self._postgres.pool.fetchrow(_ACTIVATE, user_id)
        return None if record is None else _user(record)

    async def update_profile(
        self, user_id: str, changes: Mapping[ProfileField, str | None]
    ) -> User | None:
        """Обновить только переданные поля профиля; None — пользователя нет."""
        if not changes:
            return await self.get_by_id(user_id)
        fields = list(changes)
        # Имена колонок — только из ProfileField, значения — параметрами запроса
        assignments = ", ".join(
            f"{field.value} = ${index}" for index, field in enumerate(fields, 2)
        )
        record = await self._postgres.pool.fetchrow(
            f"UPDATE users.users SET {assignments}, updated_at = now() "
            f"WHERE user_id = $1 RETURNING {_USER_COLUMNS}",
            user_id,
            *(changes[field] for field in fields),
        )
        return None if record is None else _user(record)

    async def set_password(self, email: str, password_hash: str) -> bool:
        """Сменить пароль; False — пользователя с таким email нет."""
        status = await self._postgres.pool.execute(_SET_PASSWORD, email, password_hash)
        return status == "UPDATE 1"
