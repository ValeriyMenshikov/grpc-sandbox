"""Дерево клиентов support-service из настоящего main.py (без Postgres, Redis и orders)."""

import json
import os
import subprocess
import sys

import pytest
import support_service.handlers  # noqa: F401  — регистрирует хэндлеры
from nuke_di import Dependencies
from stand_core.clients import Postgres
from stand_core.grpc import GRPC_HANDLERS, AuthPolicy, inject_handlers
from support_service.auth import AUTH_POLICIES
from support_service.chat_hub import ChatHub
from support_service.orders_client import OrdersClient
from support_service.repository import ChatRepository
from support_service.settings import SupportSettings

# main.py импортируется не как __main__, поэтому @worker не стартует; проверяем, что получилось
PROBE = """
import json
from nuke_di import DI
from support_service import main

print(json.dumps({
    "clients": [node.name for node in DI.graph().nodes],
    "handlers": sorted(signature.full_method for signature in main.HANDLERS),
    "interceptors": [type(interceptor).__name__ for interceptor in main.INTERCEPTORS],
}))
"""


def test_main_builds_client_tree() -> None:
    env = {**os.environ, "STAND_API_KEY": "key"}
    result = subprocess.run(
        [sys.executable, "-c", PROBE], env=env, capture_output=True, text=True, check=True
    )
    wiring = json.loads(result.stdout.strip().splitlines()[-1])

    assert {
        "ChatHub",
        "ChatRepository",
        "OrdersClient",
        "Postgres",
        "SupportSettings",
        "Sessions",
    } <= set(wiring["clients"])
    assert wiring["handlers"] == [
        "/support.v1.SupportService/Chat",
        "/support.v1.SupportService/GetChatHistory",
    ]
    assert wiring["interceptors"] == [
        "RequestIdInterceptor",
        "LoggingInterceptor",
        "AuthInterceptor",
        "StreamCountInterceptor",
        "ExceptionHandlingInterceptor",
    ]


@pytest.mark.usefixtures("env")
def test_handlers_inject_clients() -> None:
    container = Dependencies()

    inject_handlers(
        {s: a for s, a in GRPC_HANDLERS.items() if s.package == "support.v1"}, container
    )

    resolved = {node.client_class for node in container.graph().nodes}
    assert {ChatHub, ChatRepository, OrdersClient, Postgres, SupportSettings} <= resolved


def test_every_handler_has_user_policy() -> None:
    methods = {s.full_method for s in GRPC_HANDLERS if s.package == "support.v1"}
    assert methods == set(AUTH_POLICIES)
    assert set(AUTH_POLICIES.values()) == {AuthPolicy.USER}
