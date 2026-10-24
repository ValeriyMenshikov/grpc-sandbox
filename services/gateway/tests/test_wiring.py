"""Приложение из настоящего main.py: маршруты ТЗ 6.6, клиенты в DI, healthcheck контейнера."""

import json
import os
import socketserver
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from gateway import healthcheck
from gateway.api import router
from gateway.clients import CatalogClient, OrdersClient, UsersClient
from nuke_di import Dependencies
from stand_core import Settings

# main.py импортируется не как __main__, поэтому uvicorn не стартует; проверяем, что получилось
PROBE = """
import json
from gateway import main

print(json.dumps(sorted(
    f"{method.upper()} {path}"
    for path, operations in main.app.openapi()["paths"].items()
    for method in operations
)))
"""

ROUTES = [
    "DELETE /cart/items/{product_id}",
    "GET /cart",
    "GET /healthz",
    "GET /me",
    "GET /orders",
    "GET /orders/{order_id}",
    "GET /products",
    "GET /products/{product_id}",
    "POST /auth/confirm",
    "POST /auth/sign-in",
    "POST /auth/sign-up",
    "POST /cart/items",
    "POST /checkout",
]


def test_main_builds_app_with_all_routes() -> None:
    env = {**os.environ, "STAND_API_KEY": "key"}
    result = subprocess.run(
        [sys.executable, "-c", PROBE], env=env, capture_output=True, text=True, check=True
    )

    assert json.loads(result.stdout.strip().splitlines()[-1]) == ROUTES


def test_routes_take_grpc_clients_from_di() -> None:
    container = Dependencies()

    for route in router.routes:
        container.inject(getattr(route, "endpoint"))  # noqa: B009

    resolved = {node.client_class for node in container.graph().nodes}
    assert {UsersClient, CatalogClient, OrdersClient, Settings} <= resolved


class _Health(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200 if self.path == "/healthz" else 404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


class _Server(HTTPServer):
    def server_bind(self) -> None:
        # HTTPServer.server_bind зовёт socket.getfqdn(), а он на macOS может думать десятки секунд
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "localhost", self.server_address[1]


@pytest.fixture
def http_port(monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    server = _Server(("127.0.0.1", 0), _Health)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("HTTP_PORT", str(server.server_port))
    yield server.server_port
    server.shutdown()


@pytest.mark.usefixtures("http_port")
def test_healthcheck_ok() -> None:
    assert healthcheck.main() == 0


def test_healthcheck_fails_without_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PORT", "1")

    assert healthcheck.main() == 1
