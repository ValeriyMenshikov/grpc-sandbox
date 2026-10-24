from collections.abc import Iterator

import pytest
import structlog
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
def reset_structlog() -> Iterator[None]:
    """configure_logging() привязывает вывод к stdout теста; после теста он закрыт."""
    yield
    structlog.reset_defaults()
