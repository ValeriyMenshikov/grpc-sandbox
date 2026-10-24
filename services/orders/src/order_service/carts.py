"""Корзины в Redis: hash `cart:{user_id}` — product_id → количество."""

from nuke_di import Client
from stand_core.clients import Redis

CART_KEY_PREFIX = "cart:"
# Предел количества одной позиции: вместе с пределом цены в catalog (10**12 копеек) сумма
# корзины в копейках остаётся в int64 (Money.units)
MAX_CART_QUANTITY = 10_000

# HINCRBY, если новое количество не превысит ARGV[2]; иначе -1 и корзина не меняется
_ADD_WITHIN_LIMIT = """
local current = tonumber(redis.call("HGET", KEYS[1], ARGV[1]) or "0")
local quantity = current + tonumber(ARGV[2])
if quantity > tonumber(ARGV[3]) then
    return -1
end
return redis.call("HINCRBY", KEYS[1], ARGV[1], ARGV[2])
"""


def cart_key(user_id: str) -> str:
    return f"{CART_KEY_PREFIX}{user_id}"


class Carts(Client):
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def items(self, user_id: str) -> dict[str, int]:
        """Позиции корзины в порядке добавления (порядок полей hash в Redis)."""
        raw = await self._redis.client.hgetall(cart_key(user_id))
        # decode_responses=True: ключи и значения — str, хотя типизированы как bytes | str
        return {str(product_id): int(quantity) for product_id, quantity in raw.items()}

    async def add(self, user_id: str, product_id: str, quantity: int) -> bool:
        """Прибавить к позиции; False — итог больше `MAX_CART_QUANTITY`, корзина не менялась."""
        result = await self._redis.client.eval(
            _ADD_WITHIN_LIMIT,
            1,
            cart_key(user_id),
            product_id,
            str(quantity),
            str(MAX_CART_QUANTITY),
        )
        return int(result) >= 0

    async def remove(self, user_id: str, product_id: str) -> bool:
        """Убрать позицию; False — её не было в корзине."""
        removed: int = await self._redis.client.hdel(cart_key(user_id), product_id)
        return removed > 0

    async def clear(self, user_id: str) -> None:
        await self._redis.client.delete(cart_key(user_id))
