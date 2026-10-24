"""Корзины в Redis: hash `cart:{user_id}` — product_id → количество."""

from nuke_di import Client
from stand_core.clients import Redis

CART_KEY_PREFIX = "cart:"


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

    async def add(self, user_id: str, product_id: str, quantity: int) -> None:
        await self._redis.client.hincrby(cart_key(user_id), product_id, quantity)

    async def remove(self, user_id: str, product_id: str) -> bool:
        """Убрать позицию; False — её не было в корзине."""
        removed: int = await self._redis.client.hdel(cart_key(user_id), product_id)
        return removed > 0

    async def clear(self, user_id: str) -> None:
        await self._redis.client.delete(cart_key(user_id))
