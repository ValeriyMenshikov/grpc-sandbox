"""Политики авторизации методов support-service (ТЗ 6.0, 6.5): все методы — от имени покупателя."""

from stand_core.grpc import AuthPolicy

SUPPORT_SERVICE = "/support.v1.SupportService"

AUTH_POLICIES: dict[str, AuthPolicy] = {
    f"{SUPPORT_SERVICE}/{method}": AuthPolicy.USER for method in ("Chat", "GetChatHistory")
}
