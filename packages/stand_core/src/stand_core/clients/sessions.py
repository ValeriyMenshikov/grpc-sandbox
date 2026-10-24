"""Сессии пользователей в Redis: `session:{token}` → JSON `{"user_id", "role"}` с TTL.

Пишет их user-service (SignIn/SignOut), читает AuthInterceptor каждого сервиса.
"""

import json

from nuke_di import Client

from stand_core.clients.redis import Redis
from stand_core.grpc.context import CurrentUser, Role

SESSION_KEY_PREFIX = "session:"


def session_key(token: str) -> str:
    return f"{SESSION_KEY_PREFIX}{token}"


def encode_session(user: CurrentUser) -> str:
    return json.dumps({"user_id": user.id, "role": user.role.value})


def decode_session(raw: str | bytes) -> CurrentUser | None:
    """Пользователь из значения ключа сессии; битое значение — None (как истёкшая сессия)."""
    try:
        data = json.loads(raw)
        return CurrentUser(id=str(data["user_id"]), role=Role(data["role"]))
    except (ValueError, TypeError, KeyError):
        return None


class Sessions(Client):
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, token: str) -> CurrentUser | None:
        raw = await self._redis.client.get(session_key(token))
        return None if raw is None else decode_session(raw)

    async def save(self, token: str, user: CurrentUser, ttl_seconds: int) -> None:
        await self._redis.client.set(session_key(token), encode_session(user), ex=ttl_seconds)

    async def delete(self, token: str) -> None:
        await self._redis.client.delete(session_key(token))
