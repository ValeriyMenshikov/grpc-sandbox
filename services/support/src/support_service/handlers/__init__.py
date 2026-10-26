"""Хэндлеры support-service: импорт пакета регистрирует их в `GRPC_HANDLERS`."""

from support_service.handlers import chat_s_s, get_chat_history_u_u, get_order_timeline_u_u

__all__ = ("chat_s_s", "get_chat_history_u_u", "get_order_timeline_u_u")
