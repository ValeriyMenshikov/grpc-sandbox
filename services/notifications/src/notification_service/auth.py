"""Политики авторизации методов notification-service (ТЗ 6.0)."""

from stand_core.grpc import AuthPolicy

NOTIFICATION_SERVICE = "/notifications.v1.NotificationService"

AUTH_POLICIES: dict[str, AuthPolicy] = {
    f"{NOTIFICATION_SERVICE}/ListNotifications": AuthPolicy.SERVICE,
}
