"""Точка входа order-service: `python -m order_service.main`."""

from nuke_di import DI, BackgroundTasks, Shutdown, worker
from stand_core.grpc import (
    GRPC_HANDLERS,
    grpc_server,
    inject_handlers,
    register_auth_policies,
    resolve_interceptors,
)
from stand_core.logging import configure_logging

import order_service.handlers  # noqa: F401  — регистрирует хэндлеры
from order_service.auth import AUTH_POLICIES
from order_service.fulfillment import Fulfillment
from order_service.settings import OrderSettings

configure_logging(DI.resolve(OrderSettings).log_level)
register_auth_policies(AUTH_POLICIES)
HANDLERS = inject_handlers(GRPC_HANDLERS)  # DI.inject каждого хэндлера, до connect()
INTERCEPTORS = resolve_interceptors()  # DI.resolve каждого интерцептора (они — Client)


@worker
async def serve(shutdown: Shutdown, tasks: BackgroundTasks, fulfillment: Fulfillment) -> None:
    # Имитация доставки — asyncio-таск рядом с сервером; BackgroundTasks отменит его при остановке
    tasks.spawn(fulfillment.run(), name="fulfillment")
    async with grpc_server(HANDLERS, INTERCEPTORS):
        await shutdown.wait()
