import asyncio

from stand_core import Context, rpc
from stand_core.clients import Rabbit
from stand_core.events import (
    USER_EMAIL_CONFIRMATION_REQUESTED,
    EmailConfirmationRequested,
    email_confirmation_payload,
)
from stand_core.grpc import AlreadyExists, FieldViolation, InvalidArgument, request_id
from stand_core.logging import get_logger
from users.v1 import users_pb2

from user_service.confirm_codes import ConfirmCodes, generate_code
from user_service.convert import ROLE_FROM_PROTO, user_pb
from user_service.passwords import hash_password_async
from user_service.repository import UserRepository
from user_service.settings import UserSettings
from user_service.validation import (
    display_name_violations,
    email_violations,
    normalize_email,
    password_violations,
)

logger = get_logger(__name__)


@rpc("SignUp", package="users.v1", service="UserService")
async def sign_up(
    request: users_pb2.SignUpRequest,
    context: Context,
    repository: UserRepository,
    confirm_codes: ConfirmCodes,
    settings: UserSettings,
    rabbit: Rabbit,
) -> users_pb2.SignUpResponse:
    email = normalize_email(request.email)
    display_name = request.display_name.strip()
    role = ROLE_FROM_PROTO.get(request.role)
    violations = [
        *email_violations(email),
        *password_violations(request.password),
        *display_name_violations(display_name),
    ]
    if role is None:
        violations.append(FieldViolation("role", "must be USER_ROLE_BUYER or USER_ROLE_SELLER"))
    if violations or role is None:
        raise InvalidArgument(violations)

    password_hash = await hash_password_async(request.password)
    user = await repository.create_user(email, password_hash, display_name, role)
    if user is None:
        raise AlreadyExists("user", email)
    code = generate_code()
    await confirm_codes.save(email, code, settings.confirm_code_ttl_s)
    event = EmailConfirmationRequested(
        email=email,
        code=code,
        display_name=display_name,
        ttl_s=settings.confirm_code_ttl_s,
        request_id=request_id(),
    )
    await publish_quietly(rabbit, event, settings.confirm_publish_timeout_s)
    return users_pb2.SignUpResponse(user=user_pb(user))


async def publish_quietly(
    rabbit: Rabbit, event: EmailConfirmationRequested, timeout_s: float
) -> None:
    """Публикация события письма без ошибки наружу: пользователь создан, код уже в Redis.

    Без брокера письма не будет, но регистрация проходит (docs/decisions.md §28). Таймаут —
    потому что robust-соединение aio-pika при обрыве ждёт переподключения, а не падает сразу.
    """
    try:
        async with asyncio.timeout(timeout_s):
            await rabbit.publish(
                USER_EMAIL_CONFIRMATION_REQUESTED, email_confirmation_payload(event)
            )
    except Exception as exc:
        logger.error(
            "users.confirmation_publish_failed",
            email=event.email,
            error=str(exc) or type(exc).__name__,
        )
