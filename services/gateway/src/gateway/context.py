"""ASGI-middleware: `x-request-id` и `authorization` HTTP-запроса — в contextvars stand_core.

Оттуда их берёт базовый gRPC-клиент, как в сервисах их кладут интерцепторы. `x-request-id` из
запроса или новый uuid возвращается клиенту в заголовке ответа.
"""

import uuid

import structlog
from stand_core.grpc.context import (
    reset_authorization,
    reset_request_id,
    set_authorization,
    set_request_id,
)
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        value = headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = value
            await send(message)

        request_id_token = set_request_id(value)
        authorization_token = set_authorization(headers.get("authorization"))
        try:
            with structlog.contextvars.bound_contextvars(request_id=value):
                await self.app(scope, receive, send_with_request_id)
        finally:
            reset_authorization(authorization_token)
            reset_request_id(request_id_token)
