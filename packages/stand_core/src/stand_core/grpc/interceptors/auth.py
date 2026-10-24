"""AuthInterceptor: `x-api-key` сервиса-клиента и `authorization: Bearer` пользователя (ТЗ 6.0)."""

import hmac
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from enum import StrEnum

from nuke_di import Client

from stand_core.clients.sessions import Sessions
from stand_core.grpc.context import (
    CurrentUser,
    Role,
    reset_authorization,
    reset_current_user,
    set_authorization,
    set_current_user,
)
from stand_core.grpc.errors import PermissionDenied, Unauthenticated, abort_with_error
from stand_core.grpc.interceptors.base import Call, CallInterceptor, metadata_value
from stand_core.logging import get_logger
from stand_core.settings import Settings

API_KEY_KEY = "x-api-key"
AUTHORIZATION_KEY = "authorization"
SELLER_ROLE_REQUIRED = "SELLER_ROLE_REQUIRED"

logger = get_logger(__name__)


class AuthPolicy(StrEnum):
    SERVICE = "service"  # только x-api-key: вызов сервис → сервис
    USER = "user"  # x-api-key + токен пользователя
    SELLER = "seller"  # x-api-key + токен пользователя с ролью SELLER


# Политики по полному имени метода ("/catalog.v1.CatalogService/GetProduct"). Таблицу задаёт
# сервис через `register_auth_policies` при импорте своих хэндлеров, как и GRPC_HANDLERS.
AUTH_POLICIES: dict[str, AuthPolicy] = {}
# Метод без строки в таблице требует пользователя: забытая политика не открывает метод наружу
DEFAULT_AUTH_POLICY = AuthPolicy.USER


def register_auth_policies(policies: Mapping[str, AuthPolicy]) -> None:
    AUTH_POLICIES.update(policies)


def bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, _, token = authorization.partition(" ")
    token = token.strip()
    return token if scheme.lower() == "bearer" and token else None


class AuthInterceptor(CallInterceptor, Client):
    """Пользователь и его `authorization` кладутся в contextvars на время вызова."""

    def __init__(self, settings: Settings, sessions: Sessions) -> None:
        self._settings = settings
        self._sessions = sessions

    @asynccontextmanager
    async def around(self, call: Call) -> AsyncIterator[None]:
        try:
            user = await self.authenticate(call)
        except (Unauthenticated, PermissionDenied) as exc:
            await abort_with_error(call.context, exc)
        except Exception as exc:
            # Например, Redis сессий недоступен. ExceptionHandlingInterceptor стоит глубже и этого
            # не видит: без перехвата grpc.aio отдал бы UNKNOWN с текстом исключения
            logger.exception("grpc.auth_failed", method=call.method)
            await abort_with_error(call.context, exc)
        if user is None:
            yield
            return
        user_token = set_current_user(user)
        authorization_token = set_authorization(metadata_value(call.context, AUTHORIZATION_KEY))
        try:
            yield
        finally:
            reset_authorization(authorization_token)
            reset_current_user(user_token)

    async def authenticate(self, call: Call) -> CurrentUser | None:
        """Пользователь вызова; None — методу (политика `service`) пользователь не нужен."""
        api_key = metadata_value(call.context, API_KEY_KEY)
        if api_key is None or not hmac.compare_digest(
            api_key.encode(), self._settings.stand_api_key.encode()
        ):
            raise Unauthenticated("Missing or invalid x-api-key")

        policy = AUTH_POLICIES.get(call.method, DEFAULT_AUTH_POLICY)
        if policy is AuthPolicy.SERVICE:
            return None

        token = bearer_token(metadata_value(call.context, AUTHORIZATION_KEY))
        if token is None:
            raise Unauthenticated("Missing bearer token")
        user = await self._sessions.get(token)
        if user is None:
            raise Unauthenticated("Session is expired or does not exist")
        if policy is AuthPolicy.SELLER and user.role is not Role.SELLER:
            raise PermissionDenied(SELLER_ROLE_REQUIRED, message="Seller role required")
        return user
