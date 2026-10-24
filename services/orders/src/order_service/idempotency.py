"""Ключи идемпотентности Checkout в Redis: `idem:{user_id}:{key}` → order_id.

Пока заказ оформляется, ключ занят значением `pending:{order_id}` с коротким TTL: параллельный
повтор с тем же ключом не создаст второй заказ, а оборванный на полпути Checkout (отмена вызова)
не заблокирует ключ на сутки. После создания заказа значение — order_id с TTL `IDEMPOTENCY_TTL_S`.

TTL метки `pending` покрывает остаток deadline вызова с запасом: пока Checkout идёт, повтор
не займёт ключ заново. `commit` и `forget` меняют ключ, только если в нём всё ещё значение этого
вызова, — иначе отстающий вызов затёр бы чужую метку.
"""

import math
from dataclasses import dataclass

from nuke_di import Client
from stand_core.clients import Redis
from stand_core.grpc import time_remaining

IDEM_KEY_PREFIX = "idem:"
PENDING_PREFIX = "pending:"
# Запас сверх deadline вызова; без deadline — весь TTL (исходящие вызовы ограничены своими)
PENDING_TTL_S = 30

# SET key value EX ttl, только если текущее значение ключа — ARGV[1]
_SET_IF_EQUAL = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("SET", KEYS[1], ARGV[2], "EX", ARGV[3])
end
return false
"""
# DEL key, только если текущее значение ключа — ARGV[1]
_DELETE_IF_EQUAL = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
"""


def idempotency_key(user_id: str, key: str) -> str:
    return f"{IDEM_KEY_PREFIX}{user_id}:{key}"


def pending_ttl_s() -> int:
    """TTL метки `pending`: остаток deadline входящего вызова плюс запас."""
    remaining = time_remaining()
    return PENDING_TTL_S + (0 if remaining is None else math.ceil(remaining))


@dataclass(frozen=True)
class IdempotencyRecord:
    order_id: str
    # Checkout с этим ключом ещё идёт
    pending: bool

    def value(self) -> str:
        """Значение ключа в Redis."""
        return f"{PENDING_PREFIX}{self.order_id}" if self.pending else self.order_id


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
            idempotency_key(user_id, key),
            IdempotencyRecord(order_id, pending=True).value(),
            nx=True,
            ex=pending_ttl_s(),
        )
        return bool(claimed)

    async def commit(self, user_id: str, key: str, order_id: str, ttl_seconds: int) -> bool:
        """Закрепить за ключом заказ; False — ключ уже не занят этим вызовом."""
        committed = await self._redis.client.eval(
            _SET_IF_EQUAL,
            1,
            idempotency_key(user_id, key),
            IdempotencyRecord(order_id, pending=True).value(),
            order_id,
            str(ttl_seconds),
        )
        return bool(committed)

    async def forget(self, user_id: str, key: str, record: IdempotencyRecord) -> None:
        """Освободить ключ, если в нём всё ещё `record`."""
        await self._redis.client.eval(
            _DELETE_IF_EQUAL, 1, idempotency_key(user_id, key), record.value()
        )
