"""LoggingInterceptor: одна JSON-строка на вызов — метод, тип, request_id, статус, длительность."""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import grpc
from nuke_di import Client

from stand_core.grpc.context import request_id
from stand_core.grpc.interceptors.base import Call, CallInterceptor
from stand_core.logging import get_logger

logger = get_logger(__name__)


class LoggingInterceptor(CallInterceptor, Client):
    """Событие `grpc.call`; для стримов — `messages_received` / `messages_sent`.

    Статус — под ключом `status` (ключ `code` маскируется как код подтверждения). Тела запросов не
    логируются; секреты в остальных полях прячет процессор structlog.
    """

    @asynccontextmanager
    async def around(self, call: Call) -> AsyncIterator[None]:
        started = time.perf_counter()
        status = grpc.StatusCode.UNKNOWN
        try:
            yield
            status = call.context.code() or grpc.StatusCode.OK
        except grpc.aio.AbortError:
            status = call.context.code() or grpc.StatusCode.UNKNOWN
            raise
        except (asyncio.CancelledError, GeneratorExit):
            status = grpc.StatusCode.CANCELLED
            raise
        finally:
            fields: dict[str, object] = {
                "method": call.method,
                "grpc_type": call.grpc_type.value,
                "request_id": request_id(),
                "status": status.name,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }
            if call.grpc_type.client_streaming:
                fields["messages_received"] = call.received
            if call.grpc_type.server_streaming:
                fields["messages_sent"] = call.sent
            if status is grpc.StatusCode.OK:
                logger.info("grpc.call", **fields)
            else:
                logger.warning("grpc.call", **fields)
