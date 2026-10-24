"""Поддельный order-service на in-process сервере: GetOrder, который проверяет authorization.

Хэндлер регистрируется через `annotate`, а не `@rpc`, чтобы не попасть в общий `GRPC_HANDLERS`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from orders.v1 import orders_pb2
from stand_core import Context
from stand_core.grpc import DependencyUnavailable, NotFound, RunningServer, grpc_server
from stand_core.grpc.interceptors import ExceptionHandlingInterceptor
from stand_core.grpc.rpc import MethodSignature, annotate

from .fakes import BUYER_ID, order

BUYER_TOKEN = "buyer-token"
ORDERS = {"o-1": order("o-1", BUYER_ID), "o-2": order("o-2", "u-other")}
# Владелец по токену: так order-service узнаёт пользователя
OWNERS = {f"Bearer {BUYER_TOKEN}": BUYER_ID}


@dataclass
class Seen:
    """Что увидел order-service: metadata и остаток deadline каждого вызова, «сломан ли он»."""

    metadata: list[dict[str, str]] = field(default_factory=list)
    time_remaining: list[float | None] = field(default_factory=list)
    down: bool = False


SEEN = Seen()


async def get_order(
    request: orders_pb2.GetOrderRequest, context: Context
) -> orders_pb2.GetOrderResponse:
    metadata = {
        key: value for key, value in context.invocation_metadata() or () if isinstance(value, str)
    }
    SEEN.metadata.append(metadata)
    SEEN.time_remaining.append(context.time_remaining())
    if SEEN.down:
        raise DependencyUnavailable("postgres")
    found = ORDERS.get(request.order_id)
    if found is None or OWNERS.get(metadata.get("authorization", "")) != found.user_id:
        raise NotFound("order", request.order_id)
    return orders_pb2.GetOrderResponse(order=found)


HANDLERS = {MethodSignature("GetOrder", "OrderService", "orders.v1"): annotate(get_order)}


@asynccontextmanager
async def fake_orders() -> AsyncIterator[tuple[RunningServer, Seen]]:
    """Сервер и свежий `Seen`, который видит хэндлер."""
    global SEEN
    SEEN = Seen()
    async with grpc_server(
        HANDLERS, [ExceptionHandlingInterceptor()], port=0, host="localhost", grace=0
    ) as server:
        yield server, SEEN
