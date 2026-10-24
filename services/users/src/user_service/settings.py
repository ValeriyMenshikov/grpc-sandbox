"""Настройки user-service поверх общих `Settings` стенда."""

from stand_core import Settings


class UserSettings(Settings):
    def __init__(self) -> None:
        # Явный __init__ — как у базового Settings: иначе плагин nuke-di считает поля зависимостями
        super().__init__()

    # Время жизни сессии session:{token}
    session_ttl_s: int = 3600
    # Время жизни кода подтверждения confirm:{email}
    confirm_code_ttl_s: int = 900
    # Пароль продавца-сида seller@stand.local; хэш пишется в базу при старте сервиса
    seed_seller_password: str = "seller-password"
