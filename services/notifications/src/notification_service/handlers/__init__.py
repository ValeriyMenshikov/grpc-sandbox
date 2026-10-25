"""Хэндлеры notification-service: импорт пакета регистрирует их в `GRPC_HANDLERS`."""

from notification_service.handlers import list_notifications_u_u

__all__ = ("list_notifications_u_u",)
