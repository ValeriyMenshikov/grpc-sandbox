"""Хэндлеры user-service: импорт пакета регистрирует их в `GRPC_HANDLERS`."""

from user_service.handlers import (
    confirm_email_u_u,
    get_me_u_u,
    legacy_reset_password_u_u,
    sign_in_u_u,
    sign_out_u_u,
    sign_up_u_u,
    update_profile_u_u,
)

__all__ = (
    "confirm_email_u_u",
    "get_me_u_u",
    "legacy_reset_password_u_u",
    "sign_in_u_u",
    "sign_out_u_u",
    "sign_up_u_u",
    "update_profile_u_u",
)
