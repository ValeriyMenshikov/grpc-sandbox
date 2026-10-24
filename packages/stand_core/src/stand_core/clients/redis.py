"""Redis: клиент redis.asyncio как nuke-di Client."""

from nuke_di import Client
from redis.asyncio import Redis as AsyncRedis

from stand_core.settings import Settings


class Redis(Client):
    """Соединение с Redis (decode_responses=True: ключи и значения — str).

    В `__init__` — только зависимости; клиент создаётся и проверяется PING в `connect()`.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AsyncRedis | None = None

    @property
    def client(self) -> AsyncRedis:
        if self._client is None:
            raise RuntimeError("Redis is not connected")
        return self._client

    async def connect(self) -> None:
        url = self._settings.redis_url
        if not url:
            raise RuntimeError("REDIS_URL is not set")
        client = AsyncRedis.from_url(url, decode_responses=True)
        try:
            await client.ping()
        except BaseException:
            await client.aclose()
            raise
        self._client = client

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
