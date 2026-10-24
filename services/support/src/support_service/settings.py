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
