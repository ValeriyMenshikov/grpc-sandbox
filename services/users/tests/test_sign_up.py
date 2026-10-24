from unittest.mock import Mock

import pytest
from stand_core.grpc import AlreadyExists, FieldViolation, InvalidArgument, Role
from user_service.handlers.sign_up_u_u import sign_up
from user_service.models import UserStatus
from user_service.passwords import verify_password
from user_service.settings import UserSettings
from users.v1 import users_pb2

from .conftest import CONFIRM_CODE_TTL_S
from .fakes import FakeConfirmCodes, FakeRepository


async def test_creates_pending_buyer_and_confirm_code(
    repository: FakeRepository,
    confirm_codes: FakeConfirmCodes,
    settings: UserSettings,
    context: Mock,
) -> None:
    request = users_pb2.SignUpRequest(
        email="  New@Example.COM ", password="password1", display_name=" Иван "
    )

    response = await sign_up(request, context, repository, confirm_codes, settings)

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
    context: Mock,
) -> None:
    request = users_pb2.SignUpRequest(
        email="shop@example.com",
        password="password1",
        display_name="Магазин",
        role=users_pb2.USER_ROLE_SELLER,
    )

    response = await sign_up(request, context, repository, confirm_codes, settings)

    assert response.user.role == users_pb2.USER_ROLE_SELLER
    assert repository.users[response.user.user_id].role is Role.SELLER


async def test_invalid_fields_are_reported_together(
    repository: FakeRepository,
    confirm_codes: FakeConfirmCodes,
    settings: UserSettings,
    context: Mock,
) -> None:
    request = users_pb2.SignUpRequest(
        email="not-an-email",
        password="short",
        display_name="  ",
        role=users_pb2.UserRole.ValueType(42),
    )

    with pytest.raises(InvalidArgument) as info:
        await sign_up(request, context, repository, confirm_codes, settings)

    assert [v.field for v in info.value.field_violations] == [
        "email",
        "password",
        "display_name",
        "role",
    ]
    assert repository.users == {}
    assert confirm_codes.codes == {}


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
    context: Mock,
    email: str,
    description: str,
) -> None:
    request = users_pb2.SignUpRequest(email=email, password="password1", display_name="Иван")

    with pytest.raises(InvalidArgument) as info:
        await sign_up(request, context, repository, confirm_codes, settings)

    assert info.value.field_violations == [FieldViolation("email", description)]


async def test_taken_email_already_exists(
    repository: FakeRepository,
    confirm_codes: FakeConfirmCodes,
    settings: UserSettings,
    context: Mock,
) -> None:
    repository.add("taken@example.com")
    request = users_pb2.SignUpRequest(
        email="TAKEN@example.com", password="password1", display_name="Иван"
    )

    with pytest.raises(AlreadyExists) as info:
        await sign_up(request, context, repository, confirm_codes, settings)

    assert (info.value.resource_type, info.value.resource_name) == ("user", "taken@example.com")
    assert confirm_codes.codes == {}
