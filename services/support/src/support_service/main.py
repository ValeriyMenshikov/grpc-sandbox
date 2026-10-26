"""Точка входа support-service: `python -m support_service.main`."""

from nuke_di import DI, BackgroundTasks, Shutdown, worker
from stand_core.grpc import (
    GRPC_HANDLERS,
    grpc_server,
    inject_handlers,
    register_auth_policies,
    resolve_interceptors,
)
from stand_core.logging import configure_logging

import support_service.handlers  # noqa: F401  — регистрирует хэндлеры
from support_service.auth import AUTH_POLICIES
from support_service.order_status_consumer import OrderStatusConsumer
from support_service.settings import SupportSettings

configure_logging(DI.resolve(SupportSettings).log_level)
register_auth_policies(AUTH_POLICIES)
HANDLERS = inject_handlers(GRPC_HANDLERS)  # DI.inject каждого хэндлера, до connect()
INTERCEPTORS = resolve_interceptors()  # DI.resolve каждого интерцептора (они — Client)


@worker
async def serve(
    shutdown: Shutdown, tasks: BackgroundTasks, order_status_consumer: OrderStatusConsumer
) -> None:
    # Проекция статусов заказа — asyncio-таск рядом с сервером; BackgroundTasks отменит его.
    # Без tasks.watch(... shutdown.set()), в отличие от notification-service: брокер support не
    # обязателен, Chat работает без него, а консьюмер сам переподключается
    tasks.spawn(order_status_consumer.run(), name="order-status-consumer")
    async with grpc_server(HANDLERS, INTERCEPTORS):
        await shutdown.wait()
