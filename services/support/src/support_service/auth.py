"""Политики авторизации методов support-service (ТЗ 6.0, 6.5).

Чат — от имени покупателя; проекция статусов заказа — служебный метод, по `x-api-key`.
"""

from stand_core.grpc import AuthPolicy

SUPPORT_SERVICE = "/support.v1.SupportService"

AUTH_POLICIES: dict[str, AuthPolicy] = {
    f"{SUPPORT_SERVICE}/Chat": AuthPolicy.USER,
    f"{SUPPORT_SERVICE}/GetChatHistory": AuthPolicy.USER,
    f"{SUPPORT_SERVICE}/GetOrderTimeline": AuthPolicy.SERVICE,
}
