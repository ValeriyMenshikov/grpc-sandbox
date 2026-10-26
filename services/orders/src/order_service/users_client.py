"""Клиент к UserService от имени покупателя: email для снимка в заказе."""

import grpc
from stand_core.clients import GrpcClient
from stand_core.grpc import DependencyUnavailable
from stand_core.logging import get_logger
from users.v1 import users_pb2

logger = get_logger(__name__)

GET_ME = "/users.v1.UserService/GetMe"


class UsersClient(GrpcClient):
    address_env = "USERS_ADDR"
    dependency = "users"

    async def email(self) -> str:
        """Email текущего пользователя; "" — users-service недоступен, ответил ошибкой или пусто.

        Идёт с `authorization` покупателя: `GetMe` отвечает про владельца токена. Email в заказе —
        вспомогательный снимок для писем, поэтому ошибка соседа не роняет `Checkout`.
        """
        try:
            response = await self.unary(
                GET_ME,
                users_pb2.GetMeRequest(),
                users_pb2.GetMeResponse,
                forward_authorization=True,
            )
        except (DependencyUnavailable, grpc.aio.AioRpcError) as exc:
            logger.warning("orders.users_email_failed", error=str(exc))
            return ""
        return response.user.email
