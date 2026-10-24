"""Дерево клиентов user-service собирается из настоящего main.py (без Postgres и Redis)."""

import json
import os
import subprocess
import sys

import pytest
import user_service.handlers  # noqa: F401  — регистрирует хэндлеры
from nuke_di import Dependencies
from stand_core.clients import Postgres, Redis, Sessions
from stand_core.grpc import GRPC_HANDLERS, AuthPolicy, inject_handlers
from user_service.auth import AUTH_POLICIES
from user_service.confirm_codes import ConfirmCodes
from user_service.repository import UserRepository
from user_service.settings import UserSettings

# main.py импортируется не как __main__, поэтому @worker не стартует; проверяем, что получилось
PROBE = """
import json
from nuke_di import DI
from user_service import main

print(json.dumps({
    "clients": [node.name for node in DI.graph().nodes],
    "handlers": sorted(signature.full_method for signature in main.HANDLERS),
    "interceptors": [type(interceptor).__name__ for interceptor in main.INTERCEPTORS],
}))
"""

METHODS = [
    "ConfirmEmail",
    "GetMe",
    "LegacyResetPassword",
    "SignIn",
    "SignOut",
    "SignUp",
    "UpdateProfile",
]


def test_main_builds_client_tree() -> None:
    env = {**os.environ, "STAND_API_KEY": "key"}
    result = subprocess.run(
        [sys.executable, "-c", PROBE], env=env, capture_output=True, text=True, check=True
    )
    wiring = json.loads(result.stdout.strip().splitlines()[-1])

    assert {
        "UserRepository",
        "ConfirmCodes",
        "Postgres",
        "UserSettings",
        "Settings",
        "Sessions",
        "Redis",
    } <= set(wiring["clients"])
    assert wiring["handlers"] == [f"/users.v1.UserService/{method}" for method in METHODS]
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

    inject_handlers({s: a for s, a in GRPC_HANDLERS.items() if s.package == "users.v1"}, container)

    resolved = {node.client_class for node in container.graph().nodes}
    assert {UserRepository, ConfirmCodes, Sessions, Postgres, Redis, UserSettings} <= resolved


def test_every_handler_has_auth_policy() -> None:
    methods = {s.full_method for s in GRPC_HANDLERS if s.package == "users.v1"}
    assert methods == set(AUTH_POLICIES)
    user_methods = {m for m, policy in AUTH_POLICIES.items() if policy is AuthPolicy.USER}
    assert user_methods == {
        "/users.v1.UserService/SignOut",
        "/users.v1.UserService/GetMe",
        "/users.v1.UserService/UpdateProfile",
    }
