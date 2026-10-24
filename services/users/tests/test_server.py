"""user-service целиком на in-process сервере: интерцепторы, политики, статусы и details по сети."""

from collections.abc import AsyncIterator, Iterator

import grpc
import pytest
import user_service.handlers  # noqa: F401  — регистрирует хэндлеры
from google.protobuf.field_mask_pb2 import FieldMask
from google.rpc import error_details_pb2
from nuke_di import Dependencies
from stand_core.clients import Sessions
from stand_core.grpc import GRPC_HANDLERS, inject_handlers
from stand_core.grpc.interceptors import AUTH_POLICIES as REGISTERED_POLICIES
from stand_core.grpc.interceptors import (
    AuthInterceptor,
    ExceptionHandlingInterceptor,
    LoggingInterceptor,
    RequestIdInterceptor,
    StreamCountInterceptor,
    register_auth_policies,
)
from stand_core.grpc.server import grpc_server
from stand_core.settings import Settings
from stand_core.testing import DETAILS_KEY, rich_status
from user_service.auth import AUTH_POLICIES
from user_service.confirm_codes import ConfirmCodes
from user_service.repository import UserRepository
from users.v1 import users_pb2
from users.v1 import users_pb2_grpc as users_grpc

from .conftest import API_KEY
from .fakes import FakeConfirmCodes, FakeRepository, FakeSessions

SERVICE = (("x-api-key", API_KEY),)
# UserServiceAsyncStub есть только в .pyi (перегрузка UserServiceStub для grpc.aio.Channel),
# поэтому аннотации с ним — строкой


def user_metadata(token: str) -> tuple[tuple[str, str], ...]:
    return (*SERVICE, ("authorization", f"Bearer {token}"))


@pytest.fixture
def policies() -> Iterator[None]:
    saved = dict(REGISTERED_POLICIES)
    register_auth_policies(AUTH_POLICIES)
    yield
    REGISTERED_POLICIES.clear()
    REGISTERED_POLICIES.update(saved)


@pytest.fixture
async def stub(
    repository: FakeRepository,
    confirm_codes: FakeConfirmCodes,
    sessions: FakeSessions,
    policies: None,
) -> AsyncIterator["users_grpc.UserServiceAsyncStub"]:
    container = Dependencies()
    container.mock(UserRepository, repository)
    container.mock(ConfirmCodes, confirm_codes)
    container.mock(Sessions, sessions)
    handlers = inject_handlers(
        {s: a for s, a in GRPC_HANDLERS.items() if s.package == "users.v1"}, container
    )
    interceptors = [
        RequestIdInterceptor(),
        LoggingInterceptor(),
        AuthInterceptor(Settings(), sessions),
        StreamCountInterceptor(),
        ExceptionHandlingInterceptor(),
    ]
    async with (
        container,
        grpc_server(handlers, interceptors, port=0, host="localhost", grace=0) as server,
        grpc.aio.insecure_channel(f"localhost:{server.port}") as channel,
    ):
        yield users_grpc.UserServiceStub(channel)


async def test_sign_up_confirm_sign_in_and_out(
    stub: "users_grpc.UserServiceAsyncStub", confirm_codes: FakeConfirmCodes
) -> None:
    email = "new@example.com"
    await stub.SignUp(
        users_pb2.SignUpRequest(email=email, password="password1", display_name="Иван"),
        metadata=SERVICE,
    )
    await stub.ConfirmEmail(
        users_pb2.ConfirmEmailRequest(email=email, code=confirm_codes.codes[email]),
        metadata=SERVICE,
    )
    signed_in = await stub.SignIn(
        users_pb2.SignInRequest(email=email, password="password1"), metadata=SERVICE
    )
    token = signed_in.access_token

    me = await stub.GetMe(users_pb2.GetMeRequest(), metadata=user_metadata(token))
    updated = await stub.UpdateProfile(
        users_pb2.UpdateProfileRequest(
            profile=users_pb2.Profile(phone="+79990001122"),
            update_mask=FieldMask(paths=["phone"]),
        ),
        metadata=user_metadata(token),
    )
    await stub.SignOut(users_pb2.SignOutRequest(), metadata=user_metadata(token))
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stub.GetMe(users_pb2.GetMeRequest(), metadata=user_metadata(token))

    assert me.user.email == email
    assert me.user.status == users_pb2.USER_STATUS_ACTIVE
    assert updated.user.phone == "+79990001122"
    assert info.value.code() is grpc.StatusCode.UNAUTHENTICATED


async def test_sign_up_validation_has_bad_request(stub: "users_grpc.UserServiceAsyncStub") -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stub.SignUp(
            users_pb2.SignUpRequest(email="bad", password="short", display_name="Иван"),
            metadata=SERVICE,
        )

    assert info.value.code() is grpc.StatusCode.INVALID_ARGUMENT
    bad_request = error_details_pb2.BadRequest()
    assert rich_status(info.value).details[0].Unpack(bad_request)
    assert [v.field for v in bad_request.field_violations] == ["email", "password"]


async def test_duplicate_sign_up_already_exists(
    stub: "users_grpc.UserServiceAsyncStub", repository: FakeRepository
) -> None:
    repository.add("taken@example.com")

    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stub.SignUp(
            users_pb2.SignUpRequest(
                email="taken@example.com", password="password1", display_name="Иван"
            ),
            metadata=SERVICE,
        )

    assert info.value.code() is grpc.StatusCode.ALREADY_EXISTS
    resource = error_details_pb2.ResourceInfo()
    assert rich_status(info.value).details[0].Unpack(resource)
    assert resource.resource_name == "taken@example.com"


async def test_legacy_reset_password_is_unknown_without_details(
    stub: "users_grpc.UserServiceAsyncStub",
) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stub.LegacyResetPassword(
            users_pb2.LegacyResetPasswordRequest(email="bad", new_password="x"), metadata=SERVICE
        )

    assert info.value.code() is grpc.StatusCode.UNKNOWN
    assert info.value.details() == "Validation failed"
    assert DETAILS_KEY not in dict(info.value.trailing_metadata() or ())


@pytest.mark.parametrize("method", ["GetMe", "SignOut"])
async def test_user_methods_require_token(
    stub: "users_grpc.UserServiceAsyncStub", method: str
) -> None:
    requests = {"GetMe": users_pb2.GetMeRequest(), "SignOut": users_pb2.SignOutRequest()}
    call = getattr(stub, method)

    with pytest.raises(grpc.aio.AioRpcError) as info:
        await call(requests[method], metadata=SERVICE)

    assert info.value.code() is grpc.StatusCode.UNAUTHENTICATED


async def test_without_api_key_is_unauthenticated(stub: "users_grpc.UserServiceAsyncStub") -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await stub.SignIn(users_pb2.SignInRequest(email="a@b.c", password="password1"))
    assert info.value.code() is grpc.StatusCode.UNAUTHENTICATED
