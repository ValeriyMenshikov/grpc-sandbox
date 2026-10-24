"""Антипример LegacyResetPassword: любая ошибка — UNKNOWN «Validation failed» без details."""

from unittest.mock import Mock

import grpc
import pytest
from user_service.handlers.legacy_reset_password_u_u import LEGACY_ERROR, legacy_reset_password
from user_service.passwords import verify_password
from users.v1 import users_pb2

from .fakes import PASSWORD, FakeRepository


async def test_resets_password(repository: FakeRepository, context: Mock) -> None:
    user = repository.add("buyer@example.com")

    await legacy_reset_password(
        users_pb2.LegacyResetPasswordRequest(email="buyer@example.com", new_password="new-pass1"),
        context,
        repository,
    )

    stored = repository.users[user.user_id]
    assert verify_password("new-pass1", stored.password_hash)
    assert not verify_password(PASSWORD, stored.password_hash)
    context.abort.assert_not_called()


@pytest.mark.parametrize(
    ("email", "new_password"),
    [
        ("not-an-email", "new-pass1"),
        ("buyer@example.com", "short"),
        ("ghost@example.com", "new-pass1"),
    ],
)
async def test_any_error_is_unknown_without_details(
    repository: FakeRepository, context: Mock, email: str, new_password: str
) -> None:
    repository.add("buyer@example.com")

    with pytest.raises(grpc.aio.AbortError):
        await legacy_reset_password(
            users_pb2.LegacyResetPasswordRequest(email=email, new_password=new_password),
            context,
            repository,
        )

    context.abort.assert_awaited_once_with(grpc.StatusCode.UNKNOWN, LEGACY_ERROR)
