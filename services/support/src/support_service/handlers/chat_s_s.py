import asyncio
from collections.abc import AsyncIterator

from stand_core import Context, rpc
from stand_core.grpc import (
    FailedPrecondition,
    FieldViolation,
    InvalidArgument,
    NotFound,
    PreconditionViolation,
    current_user,
)
from support.v1 import support_pb2

from support_service.chat_hub import CLOSE_IDLE, ChatHub
from support_service.orders_client import OrdersClient
from support_service.settings import SupportSettings

CLOSE_REASON_KEY = "x-close-reason"


async def first_join(
    requests: AsyncIterator[support_pb2.ChatRequest], idle_timeout_s: float
) -> support_pb2.Join | None:
    """join из первого входящего сообщения; None — клиент молчал `idle_timeout_s`."""
    try:
        async with asyncio.timeout(idle_timeout_s):
            request = await anext(requests, None)
    except TimeoutError:
        return None
    if request is None or request.WhichOneof("payload") != "join":
        raise FailedPrecondition(
            [PreconditionViolation("JOIN_REQUIRED", "chat", "first message must be join")],
            message="First message must be join",
        )
    if not request.join.order_id:
        raise InvalidArgument([FieldViolation("join.order_id", "must not be empty")])
    return request.join


@rpc("Chat", package="support.v1", service="SupportService")
async def chat(
    request: AsyncIterator[support_pb2.ChatRequest],
    context: Context,
    chats: ChatHub,
    orders: OrdersClient,
    settings: SupportSettings,
) -> AsyncIterator[support_pb2.ChatResponse]:
    """join → joined, дальше входящие и исходящие независимо (x-items-count — интерцептор)."""
    requests = aiter(request)
    join = await first_join(requests, settings.support_idle_timeout_s)
    if join is None:
        context.set_trailing_metadata(((CLOSE_REASON_KEY, CLOSE_IDLE),))
        return
    # order-service проверяет владельца по authorization пользователя: чужой заказ — NOT_FOUND
    user = current_user()
    order = await orders.get_order(join.order_id)
    if order is None or order.user_id != user.id:
        raise NotFound("order", join.order_id)
    async with chats.session(order.order_id, user.id, orders) as session:
        yield await session.join()
        session.start(requests)
        async for event in session.events():
            yield event
    if session.close_reason is not None:
        context.set_trailing_metadata(((CLOSE_REASON_KEY, session.close_reason),))
