"""Доменные типы user-service: репозиторий и хэндлеры не зависят от proto."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from stand_core.grpc import Role


class UserStatus(StrEnum):
    # Зарегистрирован, email не подтверждён
    PENDING = "PENDING"
    # Email подтверждён, вход разрешён
    ACTIVE = "ACTIVE"


@dataclass(frozen=True)
class User:
    user_id: str
    email: str
    display_name: str
    phone: str | None
    role: Role
    status: UserStatus
    password_hash: str
    created_at: datetime
    updated_at: datetime


class ProfileField(StrEnum):
    """Редактируемые поля профиля: значение — и путь в update_mask, и колонка в users.users."""

    DISPLAY_NAME = "display_name"
    PHONE = "phone"
