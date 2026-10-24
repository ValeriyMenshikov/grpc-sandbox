import hmac

from stand_core import Context, rpc
from stand_core.grpc import (
    FailedPrecondition,
    FieldViolation,
    InvalidArgument,
    NotFound,
    PreconditionViolation,
)
from users.v1 import users_pb2

from user_service.confirm_codes import ConfirmCodes
from user_service.convert import user_pb
from user_service.models import UserStatus
from user_service.repository import UserRepository
from user_service.validation import email_violations, normalize_email


@rpc("ConfirmEmail", package="users.v1", service="UserService")
async def confirm_email(
    request: users_pb2.ConfirmEmailRequest,
    context: Context,
    repository: UserRepository,
    confirm_codes: ConfirmCodes,
) -> users_pb2.ConfirmEmailResponse:
    email = normalize_email(request.email)
    code = request.code.strip()
    violations = email_violations(email)
    if not code:
        violations.append(FieldViolation("code", "must not be empty"))
    if violations:
        raise InvalidArgument(violations)

    user = await repository.get_by_email(email)
    if user is None:
        raise NotFound("user", email)
    if user.status is UserStatus.ACTIVE:
        raise FailedPrecondition(
            [
                PreconditionViolation(
                    "EMAIL_ALREADY_CONFIRMED", f"user:{email}", "already confirmed"
                )
            ],
            message="Email is already confirmed",
        )
    expected = await confirm_codes.get(email)
    if expected is None:
        raise NotFound(
            "confirmation_code", email, description="expired or never issued, sign up again"
        )
    if not hmac.compare_digest(code.encode(), expected.encode()):
        raise InvalidArgument([FieldViolation("code", "does not match")], "Invalid code")

    activated = await repository.activate(user.user_id)
    if activated is None:
        raise NotFound("user", email)
    await confirm_codes.delete(email)
    return users_pb2.ConfirmEmailResponse(user=user_pb(activated))
