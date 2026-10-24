"""Сервис по шаблону main.py из stand_core.grpc.di; тест запускает его как скрипт."""

from catalog.v1 import catalog_pb2
from nuke_di import Client, Shutdown, worker
from stand_core import Context, rpc
from stand_core.grpc import GRPC_HANDLERS, grpc_server, inject_handlers, resolve_interceptors
from stand_core.grpc.interceptors import (
    ExceptionHandlingInterceptor,
    LoggingInterceptor,
    RequestIdInterceptor,
    StreamCountInterceptor,
)
from stand_core.logging import configure_logging


class Greeter(Client):
    def __init__(self) -> None:
        self.greeting = "not connected"

    async def connect(self) -> None:
        self.greeting = "connected"


@rpc("GetProduct", package="catalog.v1", service="CatalogService")
async def get_product(
    request: catalog_pb2.GetProductRequest, context: Context, greeter: Greeter
) -> catalog_pb2.GetProductResponse:
    return catalog_pb2.GetProductResponse(
        product=catalog_pb2.Product(product_id=request.product_id, name=greeter.greeting)
    )


configure_logging()
HANDLERS = inject_handlers(GRPC_HANDLERS)
# Как DEFAULT_INTERCEPTORS, но без AuthInterceptor: ему нужен Redis, а тест идёт без инфраструктуры
INTERCEPTORS = resolve_interceptors(
    [RequestIdInterceptor, LoggingInterceptor, StreamCountInterceptor, ExceptionHandlingInterceptor]
)


@worker
async def serve(shutdown: Shutdown) -> None:
    async with grpc_server(HANDLERS, INTERCEPTORS):
        await shutdown.wait()
