import asyncio
from collections.abc import Mapping
from typing import Any
from unittest.mock import Mock

import pytest
from stand_core.events import USER_EMAIL_CONFIRMATION_REQUESTED, parse_email_confirmation
from stand_core.grpc import AlreadyExists, FieldViolation, InvalidArgument, Role
from stand_core.grpc.context import reset_request_id, set_request_id
from structlog.testing import capture_logs
from user_service.handlers.sign_up_u_u import sign_up
from user_service.models import UserStatus
from user_service.passwords import verify_password
from user_service.settings import UserSettings
from users.v1 import users_pb2

from .conftest import CONFIRM_CODE_TTL_S
from .fakes import FakeConfirmCodes, FakeRabbit, FakeRepository


async def test_creates_pending_buyer_and_confirm_code(
    repository: FakeRepository,
    confirm_codes: FakeConfirmCodes,
    settings: UserSettings,
    rabbit: FakeRabbit,
    context: Mock,
) -> None:
    request = users_pb2.SignUpRequest(
        email="  New@Example.COM ", password="password1", display_name=" Иван "
    )

    response = await sign_up(request, context, repository, confirm_codes, settings, rabbit)

    assert response.user.email == "new@example.com"
    assert response.user.display_name == "Иван"
    assert response.user.role == users_pb2.USER_ROLE_BUYER
    assert response.user.status == users_pb2.USER_STATUS_PENDING
    assert not response.user.HasField("phone")
    stored = repository.users[response.user.user_id]
    assert stored.status is UserStatus.PENDING
    assert verify_password("password1", stored.password_hash)
    code = confirm_codes.codes["new@example.com"]
    assert len(code) == 6
    assert code.isdigit()
    assert confirm_codes.ttls["new@example.com"] == CONFIRM_CODE_TTL_S


async def test_seller_role_is_kept(
    repository: FakeRepository,
    confirm_codes: FakeConfirmCodes,
    settings: UserSettings,
    rabbit: FakeRabbit,
    context: Mock,
) -> None:
    request = users_pb2.SignUpRequest(
        email="shop@example.com",
        password="password1",
        display_name="Магазин",
        role=users_pb2.USER_ROLE_SELLER,
    )

    response = await sign_up(request, context, repository, confirm_codes, settings, rabbit)

    assert response.user.role == users_pb2.USER_ROLE_SELLER
    assert repository.users[response.user.user_id].role is Role.SELLER


async def test_invalid_fields_are_reported_together(
    repository: FakeRepository,
    confirm_codes: FakeConfirmCodes,
    settings: UserSettings,
    rabbit: FakeRabbit,
    context: Mock,
) -> None:
    request = users_pb2.SignUpRequest(
        email="not-an-email",
        password="short",
        display_name="  ",
        role=users_pb2.UserRole.ValueType(42),
    )

    with pytest.raises(InvalidArgument) as info:
        await sign_up(request, context, repository, confirm_codes, settings, rabbit)

    assert [v.field for v in info.value.field_violations] == [
        "email",
        "password",
        "display_name",
        "role",
    ]
    assert repository.users == {}
    assert confirm_codes.codes == {}
    assert rabbit.published == []


@pytest.mark.parametrize(
    ("email", "description"),
    [
        ("", "must not be empty"),
        ("a@b", "must be a valid email address"),
        ("a b@c.d", "must be a valid email address"),
        ("a@@c.d", "must be a valid email address"),
    ],
)
async def test_email_validation(
    repository: FakeRepository,
    confirm_codes: FakeConfirmCodes,
    settings: UserSettings,
    rabbit: FakeRabbit,
    context: Mock,
    email: str,
    description: str,
) -> None:
    request = users_pb2.SignUpRequest(email=email, password="password1", display_name="Иван")

    with pytest.raises(InvalidArgument) as info:
        await sign_up(request, context, repository, confirm_codes, settings, rabbit)

    assert info.value.field_violations == [FieldViolation("email", description)]


async def test_taken_email_already_exists(
    repository: FakeRepository,
    confirm_codes: FakeConfirmCodes,
    settings: UserSettings,
    rabbit: FakeRabbit,
    context: Mock,
) -> None:
    repository.add("taken@example.com")
    request = users_pb2.SignUpRequest(
        email="TAKEN@example.com", password="password1", display_name="Иван"
    )

    with pytest.raises(AlreadyExists) as info:
        await sign_up(request, context, repository, confirm_codes, settings, rabbit)

    assert (info.value.resource_type, info.value.resource_name) == ("user", "taken@example.com")
    assert confirm_codes.codes == {}
    # Письмо владельцу существующего аккаунта — спам и способ проверить, занят ли email
    assert rabbit.published == []


async def test_publishes_confirmation_event(
    repository: FakeRepository,
    confirm_codes: FakeConfirmCodes,
    settings: UserSettings,
    rabbit: FakeRabbit,
    context: Mock,
) -> None:
    request = users_pb2.SignUpRequest(
        email="New@Example.com", password="password1", display_name=" Иван "
    )
    token = set_request_id("req-1")
    try:
        await sign_up(request, context, repository, confirm_codes, settings, rabbit)
    finally:
        reset_request_id(token)

    [(routing_key, payload)] = rabbit.published
    assert routing_key == USER_EMAIL_CONFIRMATION_REQUESTED
    assert payload == {
        "email": "new@example.com",
        "code": confirm_codes.codes["new@example.com"],
        "display_name": "Иван",
        "ttl_s": CONFIRM_CODE_TTL_S,
        "request_id": "req-1",
    }
    assert parse_email_confirmation(payload).code == confirm_codes.codes["new@example.com"]


async def test_broker_failure_does_not_fail_sign_up(
    repository: FakeRepository,
    confirm_codes: FakeConfirmCodes,
    settings: UserSettings,
    rabbit: FakeRabbit,
    context: Mock,
) -> None:
    rabbit.error = ConnectionError("broker is down")
    request = users_pb2.SignUpRequest(
        email="new@example.com", password="password1", display_name="Иван"
    )

    with capture_logs() as logs:
        response = await sign_up(request, context, repository, confirm_codes, settings, rabbit)

    assert response.user.status == users_pb2.USER_STATUS_PENDING
    assert len(confirm_codes.codes["new@example.com"]) == 6
    assert rabbit.published == []
    [log] = [entry for entry in logs if entry["event"] == "users.confirmation_publish_failed"]
    assert log["log_level"] == "error"
    assert log["email"] == "new@example.com"
    assert log["error"] == "broker is down"


async def test_hanging_broker_is_cut_by_timeout(
    repository: FakeRepository,
    confirm_codes: FakeConfirmCodes,
    rabbit: FakeRabbit,
    context: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Robust-соединение без брокера ждёт переподключения — SignUp не ждёт его вечно."""
    monkeypatch.setenv("CONFIRM_PUBLISH_TIMEOUT_S", "0.01")

    async def hang(routing_key: str, payload: Mapping[str, Any]) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(rabbit, "publish", hang)
    request = users_pb2.SignUpRequest(
        email="new@example.com", password="password1", display_name="Иван"
    )

    with capture_logs() as logs:
        response = await sign_up(
            request, context, repository, confirm_codes, UserSettings(), rabbit
        )

    assert response.user.email == "new@example.com"
    assert "new@example.com" in confirm_codes.codes
    [log] = [entry for entry in logs if entry["event"] == "users.confirmation_publish_failed"]
    assert log["error"] == "TimeoutError"
