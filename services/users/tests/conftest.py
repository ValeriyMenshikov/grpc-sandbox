from collections.abc import Iterator
from unittest.mock import AsyncMock, Mock

import grpc
import pytest
from stand_core.grpc.context import CurrentUser, reset_current_user, set_current_user
from user_service.models import User
from user_service.settings import UserSettings

from .fakes import FakeConfirmCodes, FakeRabbit, FakeRepository, FakeSessions

API_KEY = "test-key"
SESSION_TTL_S = 120
CONFIRM_CODE_TTL_S = 60


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAND_API_KEY", API_KEY)
    monkeypatch.setenv("SESSION_TTL_S", str(SESSION_TTL_S))
    monkeypatch.setenv("CONFIRM_CODE_TTL_S", str(CONFIRM_CODE_TTL_S))


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def confirm_codes() -> FakeConfirmCodes:
    return FakeConfirmCodes()


@pytest.fixture
def sessions() -> FakeSessions:
    return FakeSessions()


@pytest.fixture
def rabbit() -> FakeRabbit:
    return FakeRabbit()


@pytest.fixture
def settings() -> UserSettings:
    return UserSettings()


@pytest.fixture
def context() -> Mock:
    """ServicerContext для прямого вызова хэндлера; abort ведёт себя как настоящий."""
    context = Mock()
    context.abort = AsyncMock(side_effect=grpc.aio.AbortError())
    return context


@pytest.fixture
def buyer(repository: FakeRepository) -> Iterator[User]:
    """Активный покупатель — текущий пользователь вызова."""
    user = repository.add("buyer@example.com", phone="+79990001122")
    token = set_current_user(CurrentUser(user.user_id, user.role))
    yield user
    reset_current_user(token)
