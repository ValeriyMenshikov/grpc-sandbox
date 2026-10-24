"""Настройки order-service поверх общих `Settings` стенда."""

from stand_core import Settings


class OrderSettings(Settings):
    def __init__(self) -> None:
        # Явный __init__ — как у базового Settings: иначе плагин nuke-di считает поля зависимостями
        super().__init__()

    # Сколько живёт ключ идемпотентности Checkout idem:{user_id}:{key}
    idempotency_ttl_s: int = 86_400
