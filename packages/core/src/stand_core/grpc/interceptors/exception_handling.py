"""ExceptionHandlingInterceptor: доменное исключение → статус + rich details, прочее → INTERNAL."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import grpc
from nuke_di import Client

from stand_core.grpc.errors import StandError, abort_with_error
from stand_core.grpc.interceptors.base import Call, CallInterceptor
from stand_core.logging import get_logger

logger = get_logger(__name__)


class ExceptionHandlingInterceptor(CallInterceptor, Client):
    """Последний в цепочке, ближе всех к хэндлеру.

    `context.abort()` самого хэндлера (антипример `LegacyResetPassword`) проходит как есть. Текст
    и стек прочих исключений — только в лог, клиент видит `INTERNAL: Internal error`.
    """

    @asynccontextmanager
    async def around(self, call: Call) -> AsyncIterator[None]:
        try:
            yield
        except grpc.aio.AbortError:
            raise
        except StandError as exc:
            await abort_with_error(call.context, exc)
        except Exception as exc:
            logger.exception("grpc.unhandled_exception", method=call.method)
            await abort_with_error(call.context, exc)
