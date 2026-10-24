"""support-service целиком на in-process сервере с интерцепторами стенда."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import grpc
import support_service.handlers  # noqa: F401  — регистрирует хэндлеры
from nuke_di import Dependencies
from stand_core.clients import Sessions
from stand_core.grpc import GRPC_HANDLERS, CurrentUser, Role, inject_handlers
from stand_core.grpc.interceptors import AUTH_POLICIES as REGISTERED_POLICIES
from stand_core.grpc.interceptors import (
    AuthInterceptor,
    ExceptionHandlingInterceptor,
    LoggingInterceptor,
    RequestIdInterceptor,
    StreamCountInterceptor,
    register_auth_policies,
)
from stand_core.grpc.server import grpc_server
from stand_core.settings import Settings
from support.v1 import support_pb2_grpc as support_grpc
from support_service.auth import AUTH_POLICIES
from support_service.orders_client import OrdersClient
from support_service.repository import ChatRepository

from .conftest import API_KEY
from .fakes import BUYER_ID, FakeRepository

BUYER_TOKEN = "buyer-token"
BUYER = (("x-api-key", API_KEY), ("authorization", f"Bearer {BUYER_TOKEN}"))


class FakeSessions(Sessions):
    def __init__(self) -> None:
        pass

    async def get(self, token: str) -> CurrentUser | None:
        return CurrentUser(BUYER_ID, Role.BUYER) if token == BUYER_TOKEN else None


@asynccontextmanager
async def running_support(
    repository: FakeRepository, orders: OrdersClient | None = None
) -> AsyncIterator["support_grpc.SupportServiceAsyncStub"]:
    """Стаб к серверу; `orders` None — настоящий OrdersClient к ORDERS_ADDR."""
    saved = dict(REGISTERED_POLICIES)
    register_auth_policies(AUTH_POLICIES)
    container = Dependencies()
    container.mock(ChatRepository, repository)
    if orders is not None:
        container.mock(OrdersClient, orders)
    interceptors = [
        RequestIdInterceptor(),
        LoggingInterceptor(),
        AuthInterceptor(Settings(), FakeSessions()),
        StreamCountInterceptor(),
        ExceptionHandlingInterceptor(),
    ]
    handlers = inject_handlers(
        {s: a for s, a in GRPC_HANDLERS.items() if s.package == "support.v1"}, container
    )
    try:
        async with (
            container,
            grpc_server(handlers, interceptors, port=0, host="localhost", grace=0) as server,
            grpc.aio.insecure_channel(f"localhost:{server.port}") as channel,
        ):
            yield support_grpc.SupportServiceStub(channel)
    finally:
        REGISTERED_POLICIES.clear()
        REGISTERED_POLICIES.update(saved)
