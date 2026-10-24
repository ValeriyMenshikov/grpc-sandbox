"""Общая основа интерцепторов стенда: обёртка хэндлера любого типа вызова в `around()`.

Интерцептор grpc.aio видит только `RpcMethodHandler`, а не сам вызов, поэтому `CallInterceptor`
подменяет behavior хэндлера: каждый вызов выполняется внутри `around(call)` — async context
manager'а, который видит `context`, исключения хэндлера и число сообщений в стримах.
"""

from abc import abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, aclosing
from dataclasses import dataclass
from typing import Any

import grpc

from stand_core.grpc.context import Context
from stand_core.grpc.rpc import IN_OUT_METHOD_TYPE, METHOD_MAP, GrpcTypeEnum

# Служебные сервисы: интерцепторы стенда их не трогают (без x-api-key, без логов на каждый probe)
SYSTEM_METHOD_PREFIXES = ("/grpc.health.v1.Health/", "/grpc.reflection.")

Continuation = Callable[
    [grpc.HandlerCallDetails], Awaitable["grpc.RpcMethodHandler[Any, Any] | None"]
]


@dataclass
class Call:
    """Один вызов метода, как его видит `around()`."""

    method: str  # "/catalog.v1.CatalogService/GetProduct"
    grpc_type: GrpcTypeEnum
    context: Context
    received: int = 0  # сообщений от клиента (для входящих стримов)
    sent: int = 0  # сообщений клиенту (для исходящих стримов)


def metadata_value(context: Context, key: str) -> str | None:
    """Первое текстовое значение ключа из invocation metadata (ключи gRPC — в нижнем регистре)."""
    for item_key, value in context.invocation_metadata() or ():
        if item_key == key and isinstance(value, str):
            return value
    return None


class CallInterceptor(grpc.aio.ServerInterceptor):
    @abstractmethod
    def around(self, call: Call) -> AbstractAsyncContextManager[None]:
        """Контекст, внутри которого выполняется хэндлер.

        Исключение хэндлера приходит в `__aexit__`; код после `yield` выполняется, только если
        хэндлер завершился без исключения.
        """

    async def intercept_service(
        self,
        continuation: Continuation,
        handler_call_details: grpc.HandlerCallDetails,
    ) -> "grpc.RpcMethodHandler[Any, Any] | None":
        handler = await continuation(handler_call_details)
        if handler is None or handler_call_details.method.startswith(SYSTEM_METHOD_PREFIXES):
            return handler
        return wrap_handler(handler, handler_call_details.method, self.around)


def wrap_handler(
    handler: "grpc.RpcMethodHandler[Any, Any]",
    method: str,
    around: Callable[[Call], AbstractAsyncContextManager[None]],
) -> "grpc.RpcMethodHandler[Any, Any]":
    """Такой же хэндлер, behavior которого выполняется внутри `around(Call(...))`."""
    grpc_type = IN_OUT_METHOD_TYPE[(handler.request_streaming, handler.response_streaming)]
    behavior: Callable[..., Any] | None = getattr(handler, grpc_type.value)
    if behavior is None:
        raise ValueError(f"{method}: handler has no {grpc_type} behavior")

    async def unary(request: Any, context: Context) -> Any:
        call = Call(method, grpc_type, context)
        if grpc_type.client_streaming:
            request = _count_received(request, call)
        async with around(call):
            return await behavior(request, context)

    async def streaming(request: Any, context: Context) -> AsyncIterator[Any]:
        call = Call(method, grpc_type, context)
        if grpc_type.client_streaming:
            request = _count_received(request, call)
        # Исходящий стрим — всегда async-генератор: это проверяет `rpc` при регистрации
        async with around(call), aclosing(behavior(request, context)) as result:
            async for response in result:
                call.sent += 1
                yield response

    return METHOD_MAP[grpc_type](
        streaming if grpc_type.server_streaming else unary,
        request_deserializer=handler.request_deserializer,
        response_serializer=handler.response_serializer,
    )


async def _count_received(requests: AsyncIterator[Any], call: Call) -> AsyncIterator[Any]:
    async for request in requests:
        call.received += 1
        yield request
