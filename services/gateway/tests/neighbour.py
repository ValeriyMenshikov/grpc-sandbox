"""Поддельные user- и order-service на in-process сервере: запоминают metadata вызовов.

Хэндлеры регистрируются через `annotate`, а не `@rpc`, чтобы не попасть в общий `GRPC_HANDLERS`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from orders.v1 import orders_pb2
from stand_core import Context
from stand_core.grpc import NotFound, RunningServer, grpc_server
from stand_core.grpc.interceptors import ExceptionHandlingInterceptor
from stand_core.grpc.rpc import MethodSignature, annotate
from users.v1 import users_pb2

from .fakes import order, user

# metadata каждого вызова, по порядку
SEEN: list[dict[str, str]] = []


def remember(context: Context) -> None:
    SEEN.append(
        {key: value for key, value in context.invocation_metadata() or () if isinstance(value, str)}
    )


async def get_me(request: users_pb2.GetMeRequest, context: Context) -> users_pb2.GetMeResponse:
    remember(context)
    return users_pb2.GetMeResponse(user=user())


async def checkout(
    request: orders_pb2.CheckoutRequest, context: Context
) -> orders_pb2.CheckoutResponse:
    remember(context)
    return orders_pb2.CheckoutResponse(order=order())


async def get_order(
    request: orders_pb2.GetOrderRequest, context: Context
) -> orders_pb2.GetOrderResponse:
    remember(context)
    raise NotFound("order", request.order_id)


HANDLERS = {
    MethodSignature("GetMe", "UserService", "users.v1"): annotate(get_me),
    MethodSignature("Checkout", "OrderService", "orders.v1"): annotate(checkout),
    MethodSignature("GetOrder", "OrderService", "orders.v1"): annotate(get_order),
}


@asynccontextmanager
async def fake_services() -> AsyncIterator[tuple[RunningServer, list[dict[str, str]]]]:
    """Один сервер с методами users и orders и свежий список увиденной metadata."""
    SEEN.clear()
    async with grpc_server(
        HANDLERS, [ExceptionHandlingInterceptor()], port=0, host="localhost", grace=0
    ) as server:
        yield server, SEEN
