"""Настоящие клиенты gateway по сети против поддельных сервисов: metadata, ошибки, недоступность.

httpx.AsyncClient поверх ASGI: приложение и поддельный gRPC-сервер живут в одном event loop.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from gateway.main import create_app

from .conftest import API_KEY
from .neighbour import fake_services

# Порт, на котором никто не слушает
DOWN = "localhost:1"


@pytest.fixture
async def seen(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[list[dict[str, str]]]:
    async with fake_services() as (server, seen):
        address = f"localhost:{server.port}"
        monkeypatch.setenv("USERS_ADDR", address)
        monkeypatch.setenv("ORDERS_ADDR", address)
        monkeypatch.setenv("CATALOG_ADDR", DOWN)
        monkeypatch.setenv("GRPC_DEFAULT_DEADLINE_SECONDS", "1")
        yield seen


@pytest.fixture
async def http(seen: list[dict[str, str]]) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client,
    ):
        yield client


async def test_me_sends_api_key_authorization_and_request_id(
    http: httpx.AsyncClient, seen: list[dict[str, str]]
) -> None:
    response = await http.get(
        "/me", headers={"Authorization": "Bearer token-1", "X-Request-Id": "req-1"}
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == "u-1"
    assert seen[-1]["x-api-key"] == API_KEY
    assert seen[-1]["authorization"] == "Bearer token-1"
    assert seen[-1]["x-request-id"] == "req-1"


async def test_checkout_sends_idempotency_key(
    http: httpx.AsyncClient, seen: list[dict[str, str]]
) -> None:
    response = await http.post(
        "/checkout", headers={"Authorization": "Bearer token-1", "Idempotency-Key": "key-1"}
    )

    assert response.status_code == 200
    assert seen[-1]["idempotency-key"] == "key-1"
    assert seen[-1]["authorization"] == "Bearer token-1"


async def test_checkout_without_key_sends_none(
    http: httpx.AsyncClient, seen: list[dict[str, str]]
) -> None:
    await http.post("/checkout", headers={"Authorization": "Bearer token-1"})

    assert "idempotency-key" not in seen[-1]


async def test_no_authorization_is_not_invented(
    http: httpx.AsyncClient, seen: list[dict[str, str]]
) -> None:
    await http.get("/me")

    assert "authorization" not in seen[-1]
    assert seen[-1]["x-request-id"]


async def test_rich_error_over_network(http: httpx.AsyncClient) -> None:
    response = await http.get("/orders/o-404", headers={"Authorization": "Bearer token-1"})

    assert response.status_code == 404
    assert response.json()["error"]["details"][0]["resource_name"] == "o-404"


async def test_unreachable_service_is_503(http: httpx.AsyncClient) -> None:
    response = await http.get("/products/p-1")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "UNAVAILABLE"
    assert error["details"][0]["metadata"] == {"dependency": "catalog"}
