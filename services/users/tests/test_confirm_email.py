from unittest.mock import Mock

import pytest
from stand_core.grpc import FailedPrecondition, FieldViolation, InvalidArgument, NotFound
from user_service.handlers.confirm_email_u_u import confirm_email
from user_service.models import UserStatus
from users.v1 import users_pb2

from .fakes import FakeConfirmCodes, FakeRepository

EMAIL = "new@example.com"


@pytest.fixture
def pending(repository: FakeRepository, confirm_codes: FakeConfirmCodes) -> str:
    """Зарегистрированный, но не подтверждённый пользователь с кодом 123456."""
    user = repository.add(EMAIL, status=UserStatus.PENDING)
    confirm_codes.codes[EMAIL] = "123456"
    return user.user_id


async def test_right_code_activates_user(
    repository: FakeRepository, confirm_codes: FakeConfirmCodes, context: Mock, pending: str
) -> None:
    request = users_pb2.ConfirmEmailRequest(email=" New@Example.com", code="123456")

    response = await confirm_email(request, context, repository, confirm_codes)

    assert response.user.status == users_pb2.USER_STATUS_ACTIVE
    assert repository.users[pending].status is UserStatus.ACTIVE
    assert EMAIL not in confirm_codes.codes


async def test_wrong_code_is_invalid_argument(
    repository: FakeRepository, confirm_codes: FakeConfirmCodes, context: Mock, pending: str
) -> None:
    request = users_pb2.ConfirmEmailRequest(email=EMAIL, code="654321")

    with pytest.raises(InvalidArgument) as info:
        await confirm_email(request, context, repository, confirm_codes)

    assert info.value.field_violations == [FieldViolation("code", "does not match")]
    assert repository.users[pending].status is UserStatus.PENDING
    assert confirm_codes.codes[EMAIL] == "123456"


async def test_expired_code_is_not_found(
    repository: FakeRepository, confirm_codes: FakeConfirmCodes, context: Mock, pending: str
) -> None:
    del confirm_codes.codes[EMAIL]

    with pytest.raises(NotFound) as info:
        await confirm_email(
            users_pb2.ConfirmEmailRequest(email=EMAIL, code="123456"),
            context,
            repository,
            confirm_codes,
        )

    assert info.value.resource_type == "confirmation_code"


async def test_unknown_user_is_not_found(
    repository: FakeRepository, confirm_codes: FakeConfirmCodes, context: Mock
) -> None:
    with pytest.raises(NotFound) as info:
        await confirm_email(
            users_pb2.ConfirmEmailRequest(email="ghost@example.com", code="123456"),
            context,
            repository,
            confirm_codes,
        )

    assert (info.value.resource_type, info.value.resource_name) == ("user", "ghost@example.com")


async def test_already_confirmed_is_failed_precondition(
    repository: FakeRepository, confirm_codes: FakeConfirmCodes, context: Mock
) -> None:
    repository.add(EMAIL)

    with pytest.raises(FailedPrecondition) as info:
        await confirm_email(
            users_pb2.ConfirmEmailRequest(email=EMAIL, code="123456"),
            context,
            repository,
            confirm_codes,
        )

    assert info.value.violations[0].type == "EMAIL_ALREADY_CONFIRMED"


async def test_empty_fields_are_invalid(
    repository: FakeRepository, confirm_codes: FakeConfirmCodes, context: Mock
) -> None:
    with pytest.raises(InvalidArgument) as info:
        await confirm_email(users_pb2.ConfirmEmailRequest(), context, repository, confirm_codes)

    assert [v.field for v in info.value.field_violations] == ["email", "code"]
