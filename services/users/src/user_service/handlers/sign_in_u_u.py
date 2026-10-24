import secrets
from datetime import UTC, datetime, timedelta

from stand_core import Context, rpc
from stand_core.clients import Sessions
from stand_core.grpc import CurrentUser, FailedPrecondition, PreconditionViolation, Unauthenticated
from users.v1 import users_pb2

from user_service.convert import timestamp, user_pb
from user_service.models import UserStatus
from user_service.passwords import verify_password_async
from user_service.repository import UserRepository
from user_service.settings import UserSettings
from user_service.validation import normalize_email

TOKEN_BYTES = 32
# Одно сообщение на «нет пользователя» и «неверный пароль»: не выдаём, какие email заняты
INVALID_CREDENTIALS = "Invalid email or password"


@rpc("SignIn", package="users.v1", service="UserService")
async def sign_in(
    request: users_pb2.SignInRequest,
    context: Context,
    repository: UserRepository,
    sessions: Sessions,
    settings: UserSettings,
) -> users_pb2.SignInResponse:
    user = await repository.get_by_email(normalize_email(request.email))
    if user is None or not await verify_password_async(request.password, user.password_hash):
        raise Unauthenticated(INVALID_CREDENTIALS)
    if user.status is not UserStatus.ACTIVE:
        raise FailedPrecondition(
            [PreconditionViolation("EMAIL_NOT_CONFIRMED", f"user:{user.email}", "confirm email")],
            message="Email is not confirmed",
        )

    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.session_ttl_s)
    await sessions.save(token, CurrentUser(user.user_id, user.role), settings.session_ttl_s)
    return users_pb2.SignInResponse(
        access_token=token, expires_at=timestamp(expires_at), user=user_pb(user)
    )
