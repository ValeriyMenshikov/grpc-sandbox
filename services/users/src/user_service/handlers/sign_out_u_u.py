from stand_core import Context, rpc
from stand_core.clients import Sessions
from stand_core.grpc.context import authorization
from stand_core.grpc.interceptors.auth import bearer_token
from users.v1 import users_pb2


@rpc("SignOut", package="users.v1", service="UserService")
async def sign_out(
    request: users_pb2.SignOutRequest,
    context: Context,
    sessions: Sessions,
) -> users_pb2.SignOutResponse:
    # Политика user: AuthInterceptor уже проверил токен и положил заголовок в contextvar
    token = bearer_token(authorization())
    if token is not None:
        await sessions.delete(token)
    return users_pb2.SignOutResponse()
