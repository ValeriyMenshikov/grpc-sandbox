"""ListNotifications напрямую с фейковым журналом: фильтр по адресату, страницы, валидация."""

from unittest.mock import Mock

import pytest
from common.v1 import money_pb2
from notification_service.handlers.list_notifications_u_u import list_notifications
from notification_service.models import NotificationStatus
from notification_service.pagination import MAX_PAGE_SIZE, encode_page_token
from notifications.v1 import notifications_pb2
from stand_core.grpc import InvalidArgument

from .fakes import FakeRepository


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def context() -> Mock:
    context = Mock()
    context.invocation_metadata.return_value = ()
    return context


def request(
    to_email: str | None = None, page_size: int = 0, page_token: str = ""
) -> notifications_pb2.ListNotificationsRequest:
    return notifications_pb2.ListNotificationsRequest(
        to_email=to_email,
        pagination=money_pb2.Pagination(page_size=page_size, page_token=page_token),
    )


async def test_lists_newest_first_with_proto_fields(
    context: Mock, repository: FakeRepository
) -> None:
    sent = await repository.record("a@example.com", "Код", NotificationStatus.SENT)
    failed = await repository.record("", "", NotificationStatus.FAILED, "bad event")

    response = await list_notifications(request(), context, repository)

    assert [n.notification_id for n in response.notifications] == [
        failed.notification_id,
        sent.notification_id,
    ]
    assert response.notifications[0].status == notifications_pb2.NOTIFICATION_STATUS_FAILED
    assert response.notifications[0].error == "bad event"
    assert response.notifications[1].status == notifications_pb2.NOTIFICATION_STATUS_SENT
    assert response.notifications[1].created_at.ToDatetime().year == 2026
    assert response.next_page_token == ""


@pytest.mark.parametrize("to_email", ["a@example.com", "A@Example.COM"])
async def test_filters_by_recipient_ignoring_case(
    context: Mock, repository: FakeRepository, to_email: str
) -> None:
    mine = await repository.record("a@example.com", "Код", NotificationStatus.SENT)
    await repository.record("b@example.com", "Код", NotificationStatus.SENT)

    response = await list_notifications(request(to_email), context, repository)

    assert [n.notification_id for n in response.notifications] == [mine.notification_id]


async def test_empty_filter_lists_everyone(context: Mock, repository: FakeRepository) -> None:
    await repository.record("a@example.com", "Код", NotificationStatus.SENT)
    await repository.record("b@example.com", "Код", NotificationStatus.SENT)

    response = await list_notifications(request(""), context, repository)

    assert len(response.notifications) == 2


async def test_pages_cover_everything_once(context: Mock, repository: FakeRepository) -> None:
    ids = [
        (await repository.record("a@example.com", "Код", NotificationStatus.SENT)).notification_id
        for _ in range(5)
    ]

    pages: list[list[str]] = []
    token = ""
    while True:
        response = await list_notifications(
            request(page_size=2, page_token=token), context, repository
        )
        pages.append([n.notification_id for n in response.notifications])
        token = response.next_page_token
        if not token:
            break

    assert [len(page) for page in pages] == [2, 2, 1]
    assert [item for page in pages for item in page] == ids[::-1]


async def test_page_size_is_capped(context: Mock, repository: FakeRepository) -> None:
    for _ in range(MAX_PAGE_SIZE + 1):
        await repository.record("a@example.com", "Код", NotificationStatus.SENT)

    response = await list_notifications(request(page_size=1000), context, repository)

    assert len(response.notifications) == MAX_PAGE_SIZE
    assert response.next_page_token == encode_page_token(MAX_PAGE_SIZE)


@pytest.mark.parametrize(
    ("page_size", "page_token", "field"),
    [
        (-1, "", "pagination.page_size"),
        (0, "not-a-token", "pagination.page_token"),
        (0, encode_page_token(-5), "pagination.page_token"),
    ],
)
async def test_invalid_pagination_is_invalid_argument(
    context: Mock, repository: FakeRepository, page_size: int, page_token: str, field: str
) -> None:
    with pytest.raises(InvalidArgument) as info:
        await list_notifications(
            request(page_size=page_size, page_token=page_token), context, repository
        )

    assert [violation.field for violation in info.value.field_violations] == [field]
