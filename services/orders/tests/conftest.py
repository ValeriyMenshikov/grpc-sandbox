from collections.abc import Iterator
from unittest.mock import Mock

import pytest
from order_service.settings import OrderSettings
from stand_core.grpc.context import CurrentUser, Role, reset_current_user, set_current_user

from .fakes import (
    BUYER_ID,
    FakeCarts,
    FakeCatalog,
    FakeIdempotency,
    FakeRepository,
    FakeStock,
    product,
)

API_KEY = "test-key"
IDEMPOTENCY_TTL_S = 600


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAND_API_KEY", API_KEY)
    monkeypatch.setenv("IDEMPOTENCY_TTL_S", str(IDEMPOTENCY_TTL_S))


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def carts() -> FakeCarts:
    return FakeCarts()


@pytest.fixture
def idempotency() -> FakeIdempotency:
    return FakeIdempotency()


@pytest.fixture
def catalog() -> FakeCatalog:
    return FakeCatalog(
        [product("p-1", "Наушники", 1_999_90), product("p-2", "Книга", 500_00, stock=3)]
    )


@pytest.fixture
def stock() -> FakeStock:
    return FakeStock({"p-1": 10, "p-2": 3})


@pytest.fixture
def settings() -> OrderSettings:
    return OrderSettings()


@pytest.fixture
def context() -> Mock:
    """ServicerContext для прямого вызова хэндлера, без metadata."""
    context = Mock()
    context.invocation_metadata.return_value = ()
    return context


@pytest.fixture
def buyer() -> Iterator[CurrentUser]:
    user = CurrentUser(BUYER_ID, Role.BUYER)
    token = set_current_user(user)
    yield user
    reset_current_user(token)
