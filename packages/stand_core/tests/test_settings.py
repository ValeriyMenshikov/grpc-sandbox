import pytest
from nuke_di import Dependencies, InitializeDependencyError
from pydantic import ValidationError
from stand_core.settings import Settings


def test_settings_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAND_API_KEY", "key-1")
    monkeypatch.setenv("GRPC_PORT", "50099")
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://u:p@db:5432/x")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/1")
    monkeypatch.setenv("SHUTDOWN_GRACE_SECONDS", "2.5")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.stand_api_key == "key-1"
    assert settings.postgres_dsn == "postgresql://u:p@db:5432/x"
    assert settings.redis_url == "redis://cache:6379/1"
    assert settings.shutdown_grace_seconds == 2.5
    assert settings.log_level == "DEBUG"


def test_addresses_have_no_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAND_API_KEY", "key-1")
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    settings = Settings()

    assert settings.postgres_dsn is None
    assert settings.redis_url is None


def test_api_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STAND_API_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings()


def test_settings_is_singleton_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAND_API_KEY", "key-2")
    container = Dependencies()

    first = container.resolve(Settings)

    assert first is container.resolve(Settings)
    assert first.stand_api_key == "key-2"


def test_missing_env_fails_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STAND_API_KEY", raising=False)

    with pytest.raises(InitializeDependencyError, match="stand_api_key"):
        Dependencies().resolve(Settings)
