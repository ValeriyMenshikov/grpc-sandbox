from collections.abc import Iterator

import pytest
import structlog
from stand_core.grpc.interceptors.auth import AUTH_POLICIES
from stand_core.grpc.rpc import GRPC_HANDLERS


@pytest.fixture(autouse=True)
def isolated_registry() -> Iterator[None]:
    """Хэндлеры, зарегистрированные тестом, не утекают в другие тесты."""
    saved = dict(GRPC_HANDLERS)
    GRPC_HANDLERS.clear()
    yield
    GRPC_HANDLERS.clear()
    GRPC_HANDLERS.update(saved)


@pytest.fixture(autouse=True)
def isolated_auth_policies() -> Iterator[None]:
    saved = dict(AUTH_POLICIES)
    AUTH_POLICIES.clear()
    yield
    AUTH_POLICIES.clear()
    AUTH_POLICIES.update(saved)


@pytest.fixture(autouse=True)
def reset_structlog() -> Iterator[None]:
    """configure_logging() привязывает вывод к stdout теста; после теста он закрыт."""
    yield
    structlog.reset_defaults()
