"""Доменный Notification ↔ сообщения notifications.v1."""

from datetime import datetime

from google.protobuf.timestamp_pb2 import Timestamp
from notifications.v1 import notifications_pb2

from notification_service.models import Notification, NotificationStatus

STATUS_TO_PROTO: dict[NotificationStatus, notifications_pb2.NotificationStatus.ValueType] = {
    NotificationStatus.SENT: notifications_pb2.NOTIFICATION_STATUS_SENT,
    NotificationStatus.FAILED: notifications_pb2.NOTIFICATION_STATUS_FAILED,
}


def timestamp(value: datetime) -> Timestamp:
    result = Timestamp()
    result.FromDatetime(value)
    return result


def notification_pb(notification: Notification) -> notifications_pb2.Notification:
    return notifications_pb2.Notification(
        notification_id=notification.notification_id,
        to_email=notification.to_email,
        subject=notification.subject,
        status=STATUS_TO_PROTO[notification.status],
        error=notification.error,
        created_at=timestamp(notification.created_at),
    )
