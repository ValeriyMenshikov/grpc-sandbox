"""Настройки gateway поверх общих `Settings` стенда."""

from stand_core import Settings


class GatewaySettings(Settings):
    def __init__(self) -> None:
        # Явный __init__ — как у базового Settings: иначе плагин nuke-di считает поля зависимостями
        super().__init__()

    # Порт HTTP внутри контейнера (на хосте — GATEWAY_PORT)
    http_port: int = 8080
