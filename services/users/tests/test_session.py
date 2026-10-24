"""SignIn, SignOut и GetMe."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from stand_core.grpc import CurrentUser, FailedPrecondition, NotFound, Role, Unauthenticated
from stand_core.grpc.context import (
    reset_authorization,
    reset_current_user,
    set_authorization,
    set_current_user,
)
from user_service.handlers.get_me_u_u import get_me
from user_service.handlers.sign_in_u_u import INVALID_CREDENTIALS, sign_in
from user_service.handlers.sign_out_u_u import sign_out
from user_service.models import User, UserStatus
from user_service.settings import UserSettings
from users.v1 import users_pb2

from .conftest import SESSION_TTL_S
from .fakes import PASSWORD, FakeRepository, FakeSessions


async def test_sign_in_issues_session(
    repository: FakeRepository, sessions: FakeSessions, settings: UserSettings, context: Mock
) -> None:
    user = repository.add("shop@example.com", role=Role.SELLER)
    before = datetime.now(UTC)

    response = await sign_in(
        users_pb2.SignInRequest(email="Shop@Example.com", password=PASSWORD),
        context,
        repository,
        sessions,
        settings,
    )

    token = response.access_token
    assert len(token) >= 32
    assert sessions.users[token] == CurrentUser(user.user_id, Role.SELLER)
    assert sessions.ttls[token] == SESSION_TTL_S
    expires_at = response.expires_at.ToDatetime(UTC)
    assert before + timedelta(seconds=SESSION_TTL_S - 1) <= expires_at
    assert expires_at <= datetime.now(UTC) + timedelta(seconds=SESSION_TTL_S + 1)
    assert response.user.user_id == user.user_id


async def test_each_sign_in_gets_new_token(
    repository: FakeRepository, sessions: FakeSessions, settings: UserSettings, context: Mock
) -> None:
    repository.add("buyer@example.com")
    request = users_pb2.SignInRequest(email="buyer@example.com", password=PASSWORD)

    first = await sign_in(request, context, repository, sessions, settings)
    second = await sign_in(request, context, repository, sessions, settings)

    assert first.access_token != second.access_token
    assert len(sessions.users) == 2


@pytest.mark.parametrize(
    ("email", "password"),
    [("buyer@example.com", "wrong-password"), ("ghost@example.com", PASSWORD)],
)
async def test_bad_credentials_are_unauthenticated(
    repository: FakeRepository,
    sessions: FakeSessions,
    settings: UserSettings,
    context: Mock,
    email: str,
    password: str,
) -> None:
    repository.add("buyer@example.com")

    with pytest.raises(Unauthenticated) as info:
        await sign_in(
            users_pb2.SignInRequest(email=email, password=password),
            context,
            repository,
            sessions,
            settings,
        )

    assert info.value.message == INVALID_CREDENTIALS
    assert sessions.users == {}


async def test_unconfirmed_email_is_failed_precondition(
    repository: FakeRepository, sessions: FakeSessions, settings: UserSettings, context: Mock
) -> None:
    repository.add("new@example.com", status=UserStatus.PENDING)

    with pytest.raises(FailedPrecondition) as info:
        await sign_in(
            users_pb2.SignInRequest(email="new@example.com", password=PASSWORD),
            context,
            repository,
            sessions,
            settings,
        )

    assert info.value.violations[0].type == "EMAIL_NOT_CONFIRMED"
    assert sessions.users == {}


@pytest.fixture
def signed_in(sessions: FakeSessions, buyer: User) -> Iterator[str]:
    """Сессия покупателя и его заголовок authorization, как их оставляет AuthInterceptor."""
    sessions.users["token-1"] = CurrentUser(buyer.user_id, buyer.role)
    sessions.users["token-2"] = CurrentUser(buyer.user_id, buyer.role)
    token = set_authorization("Bearer token-1")
    yield "token-1"
    reset_authorization(token)


async def test_sign_out_deletes_only_current_session(
    sessions: FakeSessions, context: Mock, signed_in: str
) -> None:
    await sign_out(users_pb2.SignOutRequest(), context, sessions)

    assert signed_in not in sessions.users
    assert "token-2" in sessions.users


async def test_get_me_returns_current_user(
    repository: FakeRepository, context: Mock, buyer: User
) -> None:
    response = await get_me(users_pb2.GetMeRequest(), context, repository)

    assert response.user.user_id == buyer.user_id
    assert response.user.email == "buyer@example.com"
    assert response.user.phone == "+79990001122"
    assert response.user.status == users_pb2.USER_STATUS_ACTIVE


async def test_get_me_for_deleted_user_is_not_found(
    repository: FakeRepository, context: Mock
) -> None:
    token = set_current_user(CurrentUser("gone", Role.BUYER))
    try:
        with pytest.raises(NotFound):
            await get_me(users_pb2.GetMeRequest(), context, repository)
    finally:
        reset_current_user(token)


async def test_get_me_without_user_is_unauthenticated(
    repository: FakeRepository, context: Mock
) -> None:
    with pytest.raises(Unauthenticated):
        await get_me(users_pb2.GetMeRequest(), context, repository)
