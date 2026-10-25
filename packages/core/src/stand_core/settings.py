"""Настройки стенда: только переменные окружения (.env), без захардкоженных адресов."""

from typing import Any

from nuke_di import Client
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings, Client):
    """Общие настройки сервисов стенда.

    nuke-di Client-синглтон: хэндлеры и клиенты получают его по type hint. Адреса Postgres, Redis и
    RabbitMQ не имеют значений по умолчанию: сервис, которому они нужны, без них не стартует
    (см. `Postgres`, `Redis`, `Rabbit`). Настройки конкретного сервиса — в подклассе в коде сервиса;
    подкласс тоже объявляет `__init__(self) -> None` (см. ниже).
    """

    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    def __init__(self) -> None:
        # Без явного __init__ mypy синтезирует его из полей, и плагин nuke-di считает каждое поле
        # зависимостью-клиентом. Значения pydantic-settings берёт из env сам.
        super().__init__()

    # BaseModel и Client оба объявляют эти хуки pydantic, и mypy видит конфликт баз. Settings
    # не бывает полем модели, поэтому достаточно стандартного поведения pydantic.
    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
        return handler(source)

    @classmethod
    def __get_pydantic_json_schema__(cls, schema: Any, handler: Any) -> Any:
        return handler(schema)

    log_level: str = "INFO"
    stand_api_key: str
    shutdown_grace_seconds: float = 5.0
    connect_timeout_seconds: float = 10.0
    grpc_default_deadline_seconds: float = 5.0

    postgres_dsn: str | None = None
    redis_url: str | None = None
    rabbitmq_url: str | None = None
    # Topic exchange доменных событий стенда (см. `stand_core.events`)
    events_exchange: str = "stand.events"
