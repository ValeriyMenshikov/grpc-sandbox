"""Доменные события стенда в RabbitMQ: routing key, структура тела, сериализация и разбор.

Публикующий сервис и потребитель пользуются одними функциями, поэтому формат тела описан
в одном месте. Разбор строгий к обязательным полям и терпимый к лишним: новое поле у
издателя не ломает старого потребителя.
"""

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

USER_EMAIL_CONFIRMATION_REQUESTED = "user.email_confirmation_requested"


class InvalidEvent(ValueError):
    """Тело сообщения не разбирается в событие: не JSON, нет поля или неверный тип."""


@dataclass(frozen=True)
class EmailConfirmationRequested:
    """Пользователь зарегистрировался — нужно отправить письмо с кодом подтверждения."""

    email: str
    code: str
    display_name: str
    ttl_s: int
    request_id: str | None = None


def email_confirmation_payload(event: EmailConfirmationRequested) -> dict[str, Any]:
    """Тело события для `Rabbit.publish`."""
    return asdict(event)


def parse_email_confirmation(body: bytes | str | Mapping[str, Any]) -> EmailConfirmationRequested:
    """Разбирает тело сообщения; при любой ошибке — `InvalidEvent` с понятным текстом."""
    data = _load(body)
    return EmailConfirmationRequested(
        email=_require_str(data, "email"),
        code=_require_str(data, "code"),
        display_name=_require_str(data, "display_name"),
        ttl_s=_require_positive_int(data, "ttl_s"),
        request_id=_optional_str(data, "request_id"),
    )


def _load(body: bytes | str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(body, Mapping):
        return body
    try:
        data = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidEvent(f"event body is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidEvent(f"event body must be a JSON object, got {type(data).__name__}")
    return data


def _require(data: Mapping[str, Any], name: str) -> Any:
    if name not in data:
        raise InvalidEvent(f"event field {name!r} is missing")
    return data[name]


def _require_str(data: Mapping[str, Any], name: str) -> str:
    value = _require(data, name)
    if not isinstance(value, str) or not value:
        raise InvalidEvent(f"event field {name!r} must be a non-empty string")
    return value


def _require_positive_int(data: Mapping[str, Any], name: str) -> int:
    value = _require(data, name)
    # bool — подкласс int, но `true` в ttl_s — ошибка издателя
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidEvent(f"event field {name!r} must be a positive integer")
    return value


def _optional_str(data: Mapping[str, Any], name: str) -> str | None:
    value = data.get(name)
    if value is not None and not isinstance(value, str):
        raise InvalidEvent(f"event field {name!r} must be a string or null")
    return value
