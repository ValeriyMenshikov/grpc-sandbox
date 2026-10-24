"""Контекст вызова: алиас ServicerContext и contextvars (request_id, текущий пользователь)."""

from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeAlias

import grpc

from stand_core.grpc.errors import Unauthenticated

# Не `type Context = ...`: в рантайме нужен настоящий класс, а не TypeAliasType
Context: TypeAlias = grpc.aio.ServicerContext[Any, Any]  # noqa: UP040


class Role(StrEnum):
    BUYER = "BUYER"
    SELLER = "SELLER"


@dataclass(frozen=True)
class CurrentUser:
    id: str
    role: Role


_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_current_user: ContextVar[CurrentUser | None] = ContextVar("current_user", default=None)


def request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None) -> Token[str | None]:
    return _request_id.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


def current_user() -> CurrentUser:
    """Пользователь текущего вызова; без него — Unauthenticated (метод требует токен)."""
    user = _current_user.get()
    if user is None:
        raise Unauthenticated("User is not authenticated")
    return user


def current_user_or_none() -> CurrentUser | None:
    return _current_user.get()


def set_current_user(user: CurrentUser | None) -> Token[CurrentUser | None]:
    return _current_user.set(user)


def reset_current_user(token: Token[CurrentUser | None]) -> None:
    _current_user.reset(token)
