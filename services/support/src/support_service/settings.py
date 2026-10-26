"""Настройки support-service поверх общих `Settings` стенда."""

from stand_core import Settings


class SupportSettings(Settings):
    def __init__(self) -> None:
        # Явный __init__ — как у базового Settings: иначе плагин nuke-di считает поля зависимостями
        super().__init__()

    # Через столько после join оператор «печатает» и здоровается
    support_agent_delay_ms: int = 1500
    # Столько секунд без сообщений клиента — и Chat завершается OK с x-close-reason: idle
    support_idle_timeout_s: float = 60.0
    # Очередь событий order.status_changed (проекция support.order_events) и её dead-letter:
    # туда уходят битые события и события с неизвестным статусом
    order_events_queue: str = "support.order_events"
    order_events_dead_letter_exchange: str = "support.order_events.dead"
    order_events_dead_letter_queue: str = "support.order_events.dead"
    # Пауза перед переподключением консьюмера к брокеру: удваивается после каждой неудачи
    # до максимума и сбрасывается, когда подключение удалось
    order_events_reconnect_delay_s: float = 1.0
    order_events_reconnect_max_delay_s: float = 30.0
