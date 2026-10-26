"""Доменный Notification → notifications.v1 и фейковый журнал."""

from notification_service.convert import STATUS_TO_PROTO, notification_pb
from notification_service.models import NotificationStatus
from notifications.v1 import notifications_pb2

from .fakes import FakeRepository


async def test_notification_pb() -> None:
    repository = FakeRepository()
    notification = await repository.record(
        "a@example.com", "Код", NotificationStatus.FAILED, "smtp down"
    )

    message = notification_pb(notification)

    assert message.notification_id == notification.notification_id
    assert (message.to_email, message.subject, message.error) == (
        "a@example.com",
        "Код",
        "smtp down",
    )
    assert message.status == notifications_pb2.NOTIFICATION_STATUS_FAILED
    assert message.created_at.ToDatetime().replace(tzinfo=notification.created_at.tzinfo) == (
        notification.created_at
    )


async def test_fake_repository_filters_and_pages() -> None:
    repository = FakeRepository()
    first = await repository.record("A@example.com", "s", NotificationStatus.SENT)
    await repository.record("b@example.com", "s", NotificationStatus.SENT)
    third = await repository.record("a@example.com", "s", NotificationStatus.SENT)

    found = await repository.list_notifications("a@EXAMPLE.com", 0, 10)
    page = await repository.list_notifications(None, 2, 1)

    assert [n.notification_id for n in found] == [third.notification_id, first.notification_id]
    assert [n.notification_id for n in page] == [first.notification_id]


def test_every_status_has_proto_value() -> None:
    assert set(STATUS_TO_PROTO) == set(NotificationStatus)
    assert STATUS_TO_PROTO[NotificationStatus.SKIPPED] == (
        notifications_pb2.NOTIFICATION_STATUS_SKIPPED
    )
