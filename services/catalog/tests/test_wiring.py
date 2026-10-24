"""Дерево клиентов catalog-service собирается из настоящего main.py (без Postgres и Redis)."""

import json
import os
import subprocess
import sys

import catalog_service.handlers  # noqa: F401  — регистрирует хэндлеры
import pytest
from catalog_service.auth import AUTH_POLICIES
from catalog_service.repository import CatalogRepository
from catalog_service.settings import CatalogSettings
from nuke_di import Dependencies
from stand_core.clients import Postgres
from stand_core.grpc import GRPC_HANDLERS, AuthPolicy, inject_handlers

# main.py импортируется не как __main__, поэтому @worker не стартует; проверяем, что получилось
PROBE = """
import json
from nuke_di import DI
from catalog_service import main

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
        "CatalogRepository",
        "Postgres",
        "CatalogSettings",
        "Settings",
        "Sessions",
        "Redis",
    } <= set(wiring["clients"])
    assert wiring["handlers"] == sorted(
        [
            "/catalog.v1.CatalogService/ExportProducts",
            "/catalog.v1.CatalogService/GetProduct",
            "/catalog.v1.CatalogService/ImportProducts",
            "/catalog.v1.CatalogService/SearchProducts",
            "/catalog.v1.StockService/GetStock",
            "/catalog.v1.StockService/ReleaseStock",
            "/catalog.v1.StockService/ReserveStock",
            "/catalog.v2.CatalogService/GetProduct",
            "/catalog.v2.CatalogService/SearchProducts",
        ]
    )
    assert wiring["interceptors"] == [
        "RequestIdInterceptor",
        "LoggingInterceptor",
        "AuthInterceptor",
        "StreamCountInterceptor",
        "ExceptionHandlingInterceptor",
    ]


@pytest.mark.usefixtures("env")
def test_handlers_inject_repository_and_settings() -> None:
    container = Dependencies()

    catalog = {s: a for s, a in GRPC_HANDLERS.items() if s.package.startswith("catalog.")}
    inject_handlers(catalog, container)

    resolved = {node.client_class for node in container.graph().nodes}
    assert {CatalogRepository, Postgres, CatalogSettings} <= resolved


def test_every_handler_has_auth_policy() -> None:

    methods = {s.full_method for s in GRPC_HANDLERS if s.package.startswith("catalog.")}
    assert methods <= set(AUTH_POLICIES)
    assert AUTH_POLICIES["/catalog.v1.CatalogService/ImportProducts"] is AuthPolicy.SELLER
    assert AUTH_POLICIES["/catalog.v1.CatalogService/ExportProducts"] is AuthPolicy.SELLER
