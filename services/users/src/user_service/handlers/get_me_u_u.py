from stand_core import Context, rpc
from stand_core.grpc import NotFound, current_user
from users.v1 import users_pb2

from user_service.convert import user_pb
from user_service.repository import UserRepository


@rpc("GetMe", package="users.v1", service="UserService")
async def get_me(
    request: users_pb2.GetMeRequest,
    context: Context,
    repository: UserRepository,
) -> users_pb2.GetMeResponse:
    user_id = current_user().id
    user = await repository.get_by_id(user_id)
    if user is None:
        # Сессия жива, а пользователя уже нет (например, после make reset)
        raise NotFound("user", user_id)
    return users_pb2.GetMeResponse(user=user_pb(user))
