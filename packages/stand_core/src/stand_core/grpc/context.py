"""Контекст вызова: алиас ServicerContext и contextvars входящего вызова.

Интерцепторы кладут сюда request_id, текущего пользователя, его `authorization` и deadline вызова,
а базовый клиент к соседям (`stand_core.clients.grpc_client`) пробрасывает их дальше.
"""

import time
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
# Значение заголовка `authorization` пользователя, прошедшего AuthInterceptor
_authorization: ContextVar[str | None] = ContextVar("authorization", default=None)
# Deadline входящего вызова по time.monotonic(); None — у вызова нет deadline
_deadline: ContextVar[float | None] = ContextVar("deadline", default=None)


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


def authorization() -> str | None:
    return _authorization.get()


def set_authorization(value: str | None) -> Token[str | None]:
    return _authorization.set(value)


def reset_authorization(token: Token[str | None]) -> None:
    _authorization.reset(token)


def time_remaining() -> float | None:
    """Сколько секунд осталось до deadline входящего вызова (не меньше 0); None — deadline нет."""
    deadline = _deadline.get()
    if deadline is None:
        return None
    return max(deadline - time.monotonic(), 0.0)


def set_time_remaining(seconds: float | None) -> Token[float | None]:
    return _deadline.set(None if seconds is None else time.monotonic() + seconds)


def reset_time_remaining(token: Token[float | None]) -> None:
    _deadline.reset(token)
