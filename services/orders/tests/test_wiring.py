"""Дерево клиентов order-service собирается из настоящего main.py (без Postgres, Redis, catalog)."""

import json
import os
import subprocess
import sys

import order_service.handlers  # noqa: F401  — регистрирует хэндлеры
import pytest
from nuke_di import Dependencies
from order_service.auth import AUTH_POLICIES
from order_service.carts import Carts
from order_service.catalog_client import CatalogClient
from order_service.events import OrderEvents
from order_service.idempotency import IdempotencyKeys
from order_service.repository import OrderRepository
from order_service.settings import OrderSettings
from order_service.stock_client import StockClient
from stand_core.clients import Postgres, Redis
from stand_core.grpc import GRPC_HANDLERS, AuthPolicy, inject_handlers

# main.py импортируется не как __main__, поэтому @worker не стартует; проверяем, что получилось
PROBE = """
import json
from nuke_di import DI
from order_service import main

print(json.dumps({
    "clients": [node.name for node in DI.graph().nodes],
    "handlers": sorted(signature.full_method for signature in main.HANDLERS),
    "interceptors": [type(interceptor).__name__ for interceptor in main.INTERCEPTORS],
}))
"""

METHODS = [
    "AddCartItem",
    "CancelOrder",
    "Checkout",
    "GetCart",
    "GetOrder",
    "ListOrders",
    "RemoveCartItem",
    "TrackOrder",
]


def test_main_builds_client_tree() -> None:
    env = {**os.environ, "STAND_API_KEY": "key"}
    result = subprocess.run(
        [sys.executable, "-c", PROBE], env=env, capture_output=True, text=True, check=True
    )
    wiring = json.loads(result.stdout.strip().splitlines()[-1])

    assert {
        "OrderRepository",
        "Carts",
        "IdempotencyKeys",
        "OrderEvents",
        "StockClient",
        "CatalogClient",
        "Postgres",
        "Redis",
        "OrderSettings",
        "Sessions",
    } <= set(wiring["clients"])
    assert wiring["handlers"] == [f"/orders.v1.OrderService/{method}" for method in METHODS]
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

    inject_handlers({s: a for s, a in GRPC_HANDLERS.items() if s.package == "orders.v1"}, container)

    resolved = {node.client_class for node in container.graph().nodes}
    assert {
        OrderRepository,
        Carts,
        IdempotencyKeys,
        OrderEvents,
        StockClient,
        CatalogClient,
        Postgres,
        Redis,
        OrderSettings,
    } <= resolved


def test_every_handler_has_user_policy() -> None:
    methods = {s.full_method for s in GRPC_HANDLERS if s.package == "orders.v1"}
    assert methods == set(AUTH_POLICIES)
    assert set(AUTH_POLICIES.values()) == {AuthPolicy.USER}
