"""StreamCountInterceptor: trailing metadata `x-items-count` у server-stream и bidi."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from nuke_di import Client

from stand_core.grpc.interceptors.base import Call, CallInterceptor

ITEMS_COUNT_KEY = "x-items-count"


class StreamCountInterceptor(CallInterceptor, Client):
    """Число отправленных сообщений, добавленное к trailing metadata хэндлера.

    Только при успешном завершении стрима: после `context.abort()` trailing metadata уже не
    меняется (её фиксирует abort).
    """

    @asynccontextmanager
    async def around(self, call: Call) -> AsyncIterator[None]:
        yield
        if call.grpc_type.server_streaming:
            context = call.context
            context.set_trailing_metadata(
                (*(context.trailing_metadata() or ()), (ITEMS_COUNT_KEY, str(call.sent)))
            )
