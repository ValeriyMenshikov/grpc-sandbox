"""Точка входа catalog-service: `python -m catalog_service.main`."""

from nuke_di import DI, Shutdown, worker
from stand_core.grpc import (
    GRPC_HANDLERS,
    grpc_server,
    inject_handlers,
    register_auth_policies,
    resolve_interceptors,
)
from stand_core.logging import configure_logging

import catalog_service.handlers  # noqa: F401  — регистрирует хэндлеры
from catalog_service.auth import AUTH_POLICIES
from catalog_service.settings import CatalogSettings

configure_logging(DI.resolve(CatalogSettings).log_level)
register_auth_policies(AUTH_POLICIES)
HANDLERS = inject_handlers(GRPC_HANDLERS)  # DI.inject каждого хэндлера, до connect()
INTERCEPTORS = resolve_interceptors()  # DI.resolve каждого интерцептора (они — Client)


@worker
async def serve(shutdown: Shutdown) -> None:
    async with grpc_server(HANDLERS, INTERCEPTORS):
        await shutdown.wait()
