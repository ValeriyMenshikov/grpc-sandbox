"""Ключи идемпотентности Checkout в Redis: `idem:{user_id}:{key}` → order_id.

Пока заказ оформляется, ключ занят значением `pending:{order_id}` с коротким TTL: параллельный
повтор с тем же ключом не создаст второй заказ, а оборванный на полпути Checkout (отмена вызова)
не заблокирует ключ на сутки. После создания заказа значение — order_id с TTL `IDEMPOTENCY_TTL_S`.
"""

from dataclasses import dataclass

from nuke_di import Client
from stand_core.clients import Redis

IDEM_KEY_PREFIX = "idem:"
PENDING_PREFIX = "pending:"
# Дольше любого разумного deadline Checkout
PENDING_TTL_S = 30


def idempotency_key(user_id: str, key: str) -> str:
    return f"{IDEM_KEY_PREFIX}{user_id}:{key}"


@dataclass(frozen=True)
class IdempotencyRecord:
    order_id: str
    # Checkout с этим ключом ещё идёт
    pending: bool


class IdempotencyKeys(Client):
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, user_id: str, key: str) -> IdempotencyRecord | None:
        value = await self._redis.client.get(idempotency_key(user_id, key))
        if value is None:
            return None
        raw = str(value)
        if raw.startswith(PENDING_PREFIX):
            return IdempotencyRecord(raw.removeprefix(PENDING_PREFIX), pending=True)
        return IdempotencyRecord(raw, pending=False)

    async def claim(self, user_id: str, key: str, order_id: str) -> bool:
        """Занять ключ под оформляемый заказ; False — ключ уже занят."""
        claimed = await self._redis.client.set(
            idempotency_key(user_id, key), f"{PENDING_PREFIX}{order_id}", nx=True, ex=PENDING_TTL_S
        )
        return bool(claimed)

    async def commit(self, user_id: str, key: str, order_id: str, ttl_seconds: int) -> None:
        await self._redis.client.set(idempotency_key(user_id, key), order_id, ex=ttl_seconds)

    async def forget(self, user_id: str, key: str) -> None:
        await self._redis.client.delete(idempotency_key(user_id, key))
