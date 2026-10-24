import pytest
from nuke_di import Dependencies
from stand_core.clients import Postgres, Redis
from stand_core.settings import Settings


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch) -> Dependencies:
    monkeypatch.setenv("STAND_API_KEY", "key")
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    return Dependencies()


def test_clients_resolve_without_io(container: Dependencies) -> None:
    postgres = container.resolve(Postgres)
    redis = container.resolve(Redis)

    # Пул и соединение появляются только в connect()
    with pytest.raises(RuntimeError, match="not connected"):
        _ = postgres.pool
    with pytest.raises(RuntimeError, match="not connected"):
        _ = redis.client


def test_clients_share_settings_singleton(container: Dependencies) -> None:
    settings = container.resolve(Settings)

    assert container.resolve(Postgres) is container.resolve(Postgres)
    assert container.graph() is not None
    assert container.resolve(Settings) is settings


async def test_postgres_connect_requires_dsn(container: Dependencies) -> None:
    with pytest.raises(RuntimeError, match="POSTGRES_DSN"):
        await container.resolve(Postgres).connect()


async def test_redis_connect_requires_url(container: Dependencies) -> None:
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        await container.resolve(Redis).connect()


async def test_disconnect_without_connect_is_noop(container: Dependencies) -> None:
    await container.resolve(Postgres).disconnect()
    await container.resolve(Redis).disconnect()
