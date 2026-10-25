"""Дерево клиентов notification-service — из настоящего main.py (без Postgres и Rabbit)."""

import json
import os
import subprocess
import sys

import notification_service.handlers  # noqa: F401  — регистрирует хэндлеры
from notification_service.auth import AUTH_POLICIES
from notification_service.repository import NotificationRepository
from nuke_di import Dependencies
from stand_core.clients import Postgres
from stand_core.grpc import GRPC_HANDLERS, AuthPolicy, inject_handlers
from stand_core.settings import Settings

# main.py импортируется не как __main__, поэтому @worker не стартует; проверяем, что получилось
PROBE = """
import json
from nuke_di import DI
from notification_service import main

# Потребитель приходит в serve параметром @worker: без inject его в DI.graph() нет
DI.inject(main.serve)
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
        "NotificationRepository",
        "Postgres",
        "NotificationSettings",
        "Sessions",
        "EmailConsumer",
        "Rabbit",
        "Mailer",
    } <= set(wiring["clients"])
    assert wiring["handlers"] == ["/notifications.v1.NotificationService/ListNotifications"]
    assert wiring["interceptors"] == [
        "RequestIdInterceptor",
        "LoggingInterceptor",
        "AuthInterceptor",
        "StreamCountInterceptor",
        "ExceptionHandlingInterceptor",
    ]


def test_handlers_inject_clients() -> None:
    container = Dependencies()

    inject_handlers(
        {s: a for s, a in GRPC_HANDLERS.items() if s.package == "notifications.v1"}, container
    )

    resolved = {node.client_class for node in container.graph().nodes}
    assert {NotificationRepository, Postgres, Settings} <= resolved


def test_every_handler_has_service_policy() -> None:
    methods = {s.full_method for s in GRPC_HANDLERS if s.package == "notifications.v1"}
    assert methods == set(AUTH_POLICIES)
    assert set(AUTH_POLICIES.values()) == {AuthPolicy.SERVICE}
