"""Политики авторизации методов notification-service (ТЗ 6.0)."""

from stand_core.grpc import AuthPolicy

NOTIFICATION_SERVICE = "/notifications.v1.NotificationService"

# Методы появляются вместе с хэндлерами
AUTH_POLICIES: dict[str, AuthPolicy] = {}
