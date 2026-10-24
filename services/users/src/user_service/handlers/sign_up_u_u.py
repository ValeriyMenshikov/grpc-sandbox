from stand_core import Context, rpc
from stand_core.grpc import AlreadyExists, FieldViolation, InvalidArgument
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


@rpc("SignUp", package="users.v1", service="UserService")
async def sign_up(
    request: users_pb2.SignUpRequest,
    context: Context,
    repository: UserRepository,
    confirm_codes: ConfirmCodes,
    settings: UserSettings,
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
    await confirm_codes.save(email, generate_code(), settings.confirm_code_ttl_s)
    return users_pb2.SignUpResponse(user=user_pb(user))
