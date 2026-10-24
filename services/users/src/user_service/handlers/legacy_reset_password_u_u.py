import grpc
from stand_core import Context, rpc
from users.v1 import users_pb2

from user_service.passwords import hash_password_async
from user_service.repository import UserRepository
from user_service.validation import email_violations, normalize_email, password_violations

LEGACY_ERROR = "Validation failed"


@rpc("LegacyResetPassword", package="users.v1", service="UserService")
async def legacy_reset_password(
    request: users_pb2.LegacyResetPasswordRequest,
    context: Context,
    repository: UserRepository,
) -> users_pb2.LegacyResetPasswordResponse:
    """НАМЕРЕННЫЙ АНТИПРИМЕР (ТЗ 6.1) — так делать не надо, метод нужен для уроков курса.

    Любая ошибка — невалидный email, короткий пароль, неизвестный пользователь — превращается
    в `UNKNOWN: Validation failed` без details: клиент не может отличить свою ошибку от сбоя
    сервера и не знает, какое поле исправить. Правильно — `InvalidArgument` с `BadRequest`
    (см. SignUp) и `NotFound` для неизвестного пользователя. Хэндлер сам зовёт `context.abort`,
    ExceptionHandlingInterceptor пропускает такой abort как есть.
    """
    email = normalize_email(request.email)
    if email_violations(email) or password_violations(request.new_password):
        await context.abort(grpc.StatusCode.UNKNOWN, LEGACY_ERROR)
    password_hash = await hash_password_async(request.new_password)
    if not await repository.set_password(email, password_hash):
        await context.abort(grpc.StatusCode.UNKNOWN, LEGACY_ERROR)
    return users_pb2.LegacyResetPasswordResponse()
