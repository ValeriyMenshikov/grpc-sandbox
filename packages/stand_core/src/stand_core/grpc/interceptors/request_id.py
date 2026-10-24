"""RequestIdInterceptor: `x-request-id` из metadata или новый uuid — в contextvar и клиенту."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from nuke_di import Client

from stand_core.grpc.context import (
    reset_request_id,
    reset_time_remaining,
    set_request_id,
    set_time_remaining,
)
from stand_core.grpc.interceptors.base import Call, CallInterceptor, metadata_value

REQUEST_ID_KEY = "x-request-id"


class RequestIdInterceptor(CallInterceptor, Client):
    """Первый в цепочке: request_id виден логам и хэндлеру, клиент получает его в initial metadata.

    Здесь же запоминается deadline входящего вызова: базовый клиент к соседям передаёт остаток
    дальше (`stand_core.grpc.context.time_remaining`).
    """

    def __init__(self) -> None:
        pass

    @asynccontextmanager
    async def around(self, call: Call) -> AsyncIterator[None]:
        value = metadata_value(call.context, REQUEST_ID_KEY) or str(uuid.uuid4())
        await call.context.send_initial_metadata(((REQUEST_ID_KEY, value),))
        request_id_token = set_request_id(value)
        deadline_token = set_time_remaining(call.context.time_remaining())
        try:
            with structlog.contextvars.bound_contextvars(request_id=value):
                yield
        finally:
            reset_time_remaining(deadline_token)
            reset_request_id(request_id_token)
