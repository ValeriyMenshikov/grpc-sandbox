"""notification-service на in-process сервере со всеми интерцепторами; журнал — через DI.mock."""

from collections.abc import AsyncIterator, Iterator

import grpc
import notification_service.handlers  # noqa: F401  — регистрирует хэндлеры
import pytest
from common.v1 import money_pb2
from google.rpc import error_details_pb2
from notification_service.auth import AUTH_POLICIES
from notification_service.models import NotificationStatus
from notification_service.repository import NotificationRepository
from notifications.v1 import notifications_pb2
from notifications.v1 import notifications_pb2_grpc as notifications_grpc
from nuke_di import Dependencies
from stand_core.clients import Sessions
from stand_core.grpc import GRPC_HANDLERS, CurrentUser, inject_handlers
from stand_core.grpc.interceptors import AUTH_POLICIES as REGISTERED_POLICIES
from stand_core.grpc.interceptors import (
    AuthInterceptor,
    ExceptionHandlingInterceptor,
    LoggingInterceptor,
    RequestIdInterceptor,
    StreamCountInterceptor,
    register_auth_policies,
)
from stand_core.grpc.server import grpc_server
from stand_core.settings import Settings
from stand_core.testing import rich_status

from .conftest import API_KEY
from .fakes import FakeRepository

SERVICE = (("x-api-key", API_KEY),)
# NotificationServiceAsyncStub есть только в .pyi, поэтому аннотации с ним — строкой


class FakeSessions(Sessions):
    def __init__(self) -> None:
        pass

    async def get(self, token: str) -> CurrentUser | None:
        return None


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def policies() -> Iterator[None]:
    saved = dict(REGISTERED_POLICIES)
    register_auth_policies(AUTH_POLICIES)
    yield
    REGISTERED_POLICIES.clear()
    REGISTERED_POLICIES.update(saved)


@pytest.fixture
async def stub(
    repository: FakeRepository, policies: None
) -> AsyncIterator["notifications_grpc.NotificationServiceAsyncStub"]:
    container = Dependencies()
    container.mock(NotificationRepository, repository)
    interceptors = [
        RequestIdInterceptor(),
        LoggingInterceptor(),
        AuthInterceptor(Settings(), FakeSessions()),
        StreamCountInterceptor(),
        ExceptionHandlingInterceptor(),
    ]
    handlers = inject_handlers(
        {s: a for s, a in GRPC_HANDLERS.items() if s.package == "notifications.v1"}, container
    )
    async with (
        container,
        grpc_server(handlers, interceptors, port=0, host="localhost", grace=0) as server,
        grpc.aio.insecure_channel(f"localhost:{server.port}") as channel,
    ):
        yield notifications_grpc.NotificationServiceStub(channel)


async def test_list_with_api_key(
    stub: "notifications_grpc.NotificationServiceAsyncStub", repository: FakeRepository
) -> None:
    sent = await repository.record("a@example.com", "Код", NotificationStatus.SENT)
    await repository.record("b@example.com", "Код", NotificationStatus.FAILED, "smtp down")

    response = await stub.ListNotifications(
        notifications_pb2.ListNotificationsRequest(to_email="a@example.com"), metadata=SERVICE
    )

    assert [n.notification_id for n in response.notifications] == [sent.notification_id]
    assert response.notifications[0].status == notifications_pb2.NOTIFICATION_STATUS_SENT


@pytest.mark.parametrize("metadata", [(), (("x-api-key", "wrong"),)])
async def test_without_valid_api_key_is_unauthenticated(
    stub: "notifications_grpc.NotificationServiceAsyncStub",
    metadata: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stub.ListNotifications(
            notifications_pb2.ListNotificationsRequest(), metadata=metadata
        )

    assert info.value.code() is grpc.StatusCode.UNAUTHENTICATED


async def test_negative_page_size_has_bad_request(
    stub: "notifications_grpc.NotificationServiceAsyncStub",
) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stub.ListNotifications(
            notifications_pb2.ListNotificationsRequest(
                pagination=money_pb2.Pagination(page_size=-1)
            ),
            metadata=SERVICE,
        )

    assert info.value.code() is grpc.StatusCode.INVALID_ARGUMENT
    bad_request = error_details_pb2.BadRequest()
    assert rich_status(info.value).details[0].Unpack(bad_request)
    assert bad_request.field_violations[0].field == "pagination.page_size"
