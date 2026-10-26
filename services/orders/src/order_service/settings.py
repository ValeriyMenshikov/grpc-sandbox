"""Настройки order-service поверх общих `Settings` стенда."""

from stand_core import Settings


class OrderSettings(Settings):
    def __init__(self) -> None:
        # Явный __init__ — как у базового Settings: иначе плагин nuke-di считает поля зависимостями
        super().__init__()

    # Сколько живёт ключ идемпотентности Checkout idem:{user_id}:{key}
    idempotency_ttl_s: int = 86_400
    # Шаг имитации доставки: столько заказ стоит в каждом статусе до DELIVERED
    fulfillment_step_ms: int = 2000
    # Сколько ждать email покупателя от users-service в Checkout, прежде чем оформить заказ без него
    users_email_timeout_s: float = 2.0
