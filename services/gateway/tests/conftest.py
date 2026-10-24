from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from gateway.clients import CatalogClient, OrdersClient, UsersClient
from gateway.main import create_app
from nuke_di import DI

from .fakes import FakeCatalog, FakeOrders, FakeUsers

API_KEY = "test-key"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAND_API_KEY", API_KEY)


@pytest.fixture
def users() -> FakeUsers:
    return FakeUsers()


@pytest.fixture
def catalog() -> FakeCatalog:
    return FakeCatalog()


@pytest.fixture
def orders() -> FakeOrders:
    return FakeOrders()


@pytest.fixture
def http(users: FakeUsers, catalog: FakeCatalog, orders: FakeOrders) -> Iterator[TestClient]:
    """gateway с подменой всех трёх gRPC-клиентов в DI (router объявлен на глобальном DI)."""
    with (
        DI.override(UsersClient, users),
        DI.override(CatalogClient, catalog),
        DI.override(OrdersClient, orders),
        TestClient(create_app()) as client,
    ):
        yield client
