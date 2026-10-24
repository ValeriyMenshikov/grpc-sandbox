"""Коды подтверждения email в Redis: `confirm:{email}` → 6-значный код с TTL.

Письма нет: автотесты курса читают код прямо из Redis по этому ключу.
"""

import secrets

from nuke_di import Client
from stand_core.clients import Redis

CONFIRM_KEY_PREFIX = "confirm:"
CODE_DIGITS = 6


def confirm_key(email: str) -> str:
    return f"{CONFIRM_KEY_PREFIX}{email}"


def generate_code() -> str:
    return f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


class ConfirmCodes(Client):
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def save(self, email: str, code: str, ttl_seconds: int) -> None:
        await self._redis.client.set(confirm_key(email), code, ex=ttl_seconds)

    async def get(self, email: str) -> str | None:
        code = await self._redis.client.get(confirm_key(email))
        return None if code is None else str(code)

    async def delete(self, email: str) -> None:
        await self._redis.client.delete(confirm_key(email))
