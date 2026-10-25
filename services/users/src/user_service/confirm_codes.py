"""Коды подтверждения email в Redis: `confirm:{email}` → 6-значный код с TTL.

Здесь код сверяется в `ConfirmEmail`; до пользователя он доходит письмом: `SignUp` публикует
событие в RabbitMQ, notification-service отправляет его в Mailpit.
"""

import secrets

from nuke_di import Client, client_dataclass
from stand_core.clients import Redis

CONFIRM_KEY_PREFIX = "confirm:"
CODE_DIGITS = 6


def confirm_key(email: str) -> str:
    return f"{CONFIRM_KEY_PREFIX}{email}"


def generate_code() -> str:
    return f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


@client_dataclass
class ConfirmCodes(Client):
    _redis: Redis

    async def save(self, email: str, code: str, ttl_seconds: int) -> None:
        await self._redis.client.set(confirm_key(email), code, ex=ttl_seconds)

    async def get(self, email: str) -> str | None:
        code = await self._redis.client.get(confirm_key(email))
        return None if code is None else str(code)

    async def delete(self, email: str) -> None:
        await self._redis.client.delete(confirm_key(email))
