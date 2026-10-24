from stand_core import Context, rpc
from stand_core.grpc import FieldViolation, InvalidArgument, NotFound, current_user
from users.v1 import users_pb2

from user_service.convert import user_pb
from user_service.models import ProfileField
from user_service.repository import UserRepository
from user_service.validation import display_name_violations, phone_violations

ALLOWED_PATHS = ", ".join(field.value for field in ProfileField)


def profile_changes(
    request: users_pb2.UpdateProfileRequest,
) -> dict[ProfileField, str | None]:
    """Изменения профиля по update_mask; нарушения → InvalidArgument со всеми полями сразу."""
    paths = list(request.update_mask.paths)
    if not paths:
        raise InvalidArgument(
            [FieldViolation("update_mask", f"must list fields to update: {ALLOWED_PATHS}")]
        )
    violations: list[FieldViolation] = []
    changes: dict[ProfileField, str | None] = {}
    for index, path in enumerate(paths):
        try:
            field = ProfileField(path)
        except ValueError:
            violations.append(
                FieldViolation(
                    f"update_mask.paths[{index}]",
                    f"unknown path {path!r}, allowed: {ALLOWED_PATHS}",
                )
            )
            continue
        match field:
            case ProfileField.DISPLAY_NAME:
                display_name = request.profile.display_name.strip()
                violations += display_name_violations(display_name, "profile.display_name")
                changes[field] = display_name
            case ProfileField.PHONE:
                # phone в маске, но не задан в profile — телефон удаляется
                phone = request.profile.phone.strip() if request.profile.HasField("phone") else ""
                if phone:
                    violations += phone_violations(phone, "profile.phone")
                changes[field] = phone or None
    if violations:
        raise InvalidArgument(violations)
    return changes


@rpc("UpdateProfile", package="users.v1", service="UserService")
async def update_profile(
    request: users_pb2.UpdateProfileRequest,
    context: Context,
    repository: UserRepository,
) -> users_pb2.UpdateProfileResponse:
    changes = profile_changes(request)
    user_id = current_user().id
    user = await repository.update_profile(user_id, changes)
    if user is None:
        raise NotFound("user", user_id)
    return users_pb2.UpdateProfileResponse(user=user_pb(user))
