from collections.abc import Iterator
from unittest.mock import Mock

import pytest
from catalog_service.settings import CatalogSettings
from stand_core.grpc.context import CurrentUser, Role, reset_current_user, set_current_user

from .fakes import BUYER_ID, SELLER_ID, FakeRepository

API_KEY = "test-key"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAND_API_KEY", API_KEY)
    monkeypatch.setenv("IMPORT_MAX_ROWS", "5")


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def settings() -> CatalogSettings:
    return CatalogSettings()


@pytest.fixture
def context() -> Mock:
    """ServicerContext для прямого вызова хэндлера: вызов не завершён."""
    context = Mock()
    context.done.return_value = False
    return context


@pytest.fixture
def seller() -> Iterator[CurrentUser]:
    user = CurrentUser(SELLER_ID, Role.SELLER)
    token = set_current_user(user)
    yield user
    reset_current_user(token)


@pytest.fixture
def buyer() -> Iterator[CurrentUser]:
    user = CurrentUser(BUYER_ID, Role.BUYER)
    token = set_current_user(user)
    yield user
    reset_current_user(token)
