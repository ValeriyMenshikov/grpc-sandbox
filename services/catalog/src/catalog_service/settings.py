"""Настройки catalog-service поверх общих `Settings` стенда."""

from stand_core import Settings


class CatalogSettings(Settings):
    def __init__(self) -> None:
        # Явный __init__ — как у базового Settings: иначе плагин nuke-di считает поля зависимостями
        super().__init__()

    # Больше строк в одном ImportProducts → RESOURCE_EXHAUSTED + QuotaFailure
    import_max_rows: int = 10_000
