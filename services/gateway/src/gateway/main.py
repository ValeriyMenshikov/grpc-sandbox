"""Точка входа gateway: `python -m gateway.main`.

Клиенты подключает lifespan приложения (`nuke_di.fastapi.setup`), а не `@worker`: worker сам
подключал бы контейнер DI, и lifespan отказался бы стартовать на уже подключённом контейнере.
Graceful stop по SIGTERM — у uvicorn.
"""

import uvicorn
from fastapi import FastAPI
from nuke_di import DI
from nuke_di.fastapi import setup
from stand_core.logging import configure_logging

from gateway.api import router
from gateway.context import RequestContextMiddleware
from gateway.errors import install_error_handlers
from gateway.settings import GatewaySettings


def create_app() -> FastAPI:
    """Приложение на глобальном `DI`: на нём объявлен `router` (тесты подменяют клиентов в `DI`)."""
    app = FastAPI(title="grpc-stand gateway", description="BFF для веб-фронта поверх gRPC")
    setup(app)
    app.include_router(router)
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    return app


app = create_app()


def run() -> None:
    settings = DI.resolve(GatewaySettings)
    configure_logging(settings.log_level)
    uvicorn.run(
        app,
        host="0.0.0.0",  # внутри контейнера
        port=settings.http_port,
        timeout_graceful_shutdown=int(settings.shutdown_grace_seconds),
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    run()
