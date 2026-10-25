"""Логирование: structlog в JSON, одна строка на событие, секреты маскируются."""

import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

MASK = "***"

# Ключи, значения которых никогда не попадают в лог. Сравнение без учёта регистра, `-` == `_`.
_SECRET_KEYS = frozenset(
    {
        "password",
        "new_password",
        "old_password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "x_api_key",
        "api_key",
        "stand_api_key",
        "secret",
        "code",
        "confirm_code",
        "confirmation_code",
    }
)
_SECRET_SUFFIXES = ("_password", "_token", "_secret")
_BEARER = re.compile(r"(?i)\bbearer\s+\S+")


def is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in _SECRET_KEYS or normalized.endswith(_SECRET_SUFFIXES)


def mask_secrets(value: Any) -> Any:
    """Копия `value`, в которой значения секретных ключей заменены на `***`.

    Обходит вложенные dict/list/tuple (например, `MessageToDict` от запроса или metadata как
    список пар), а в строках прячет `Bearer <token>`.
    """
    if isinstance(value, Mapping):
        return {
            key: MASK if isinstance(key, str) and is_secret_key(key) else mask_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
        # Пара metadata: ("authorization", "Bearer ...")
        key, item = value
        return (key, MASK if is_secret_key(key) else mask_secrets(item))
    if isinstance(value, list | tuple):
        return type(value)(mask_secrets(item) for item in value)
    if isinstance(value, str):
        return _BEARER.sub(f"Bearer {MASK}", value)
    return value


def _mask_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    masked: MutableMapping[str, Any] = mask_secrets(event_dict)
    return masked


def configure_logging(level: str = "INFO") -> None:
    """Настроить structlog: JSON в stdout, ISO-время, уровень, маскировка секретов."""
    log_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            _mask_processor,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.typing.FilteringBoundLogger:
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger(name)
    return logger
