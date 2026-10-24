from collections.abc import Iterator
from unittest.mock import Mock

import pytest
from stand_core.grpc.context import CurrentUser, Role, reset_current_user, set_current_user
from support_service.chat_hub import ChatHub
from support_service.settings import SupportSettings

from .fakes import BUYER_ID, OTHER_ID, FakeOrders, FakeRepository, order

API_KEY = "test-key"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAND_API_KEY", API_KEY)
    # По умолчанию оператор не успевает поздороваться, а простой не наступает: тесты, которым
    # нужно приветствие или idle, выставляют свои значения
    monkeypatch.setenv("SUPPORT_AGENT_DELAY_MS", "60000")
    monkeypatch.setenv("SUPPORT_IDLE_TIMEOUT_S", "30")


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def orders() -> FakeOrders:
    return FakeOrders([order("o-1"), order("o-2", user_id=OTHER_ID)])


@pytest.fixture
def settings() -> SupportSettings:
    return SupportSettings()


@pytest.fixture
def hub(repository: FakeRepository, settings: SupportSettings) -> ChatHub:
    return ChatHub(repository, settings)


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


@pytest.fixture
def fast_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPPORT_AGENT_DELAY_MS", "20")


@pytest.fixture
def short_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPPORT_IDLE_TIMEOUT_S", "0.2")
