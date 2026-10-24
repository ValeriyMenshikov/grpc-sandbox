"""Поддельный catalog-service на in-process сервере: GetProduct, ReserveStock, ReleaseStock.

Хэндлеры регистрируются через `annotate`, а не `@rpc`, чтобы не попасть в общий `GRPC_HANDLERS`.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from catalog.v1 import catalog_pb2
from stand_core import Context
from stand_core.grpc import (
    DependencyUnavailable,
    FailedPrecondition,
    NotFound,
    PreconditionViolation,
    RunningServer,
    grpc_server,
)
from stand_core.grpc.interceptors import ExceptionHandlingInterceptor
from stand_core.grpc.rpc import MethodSignature, annotate

PRODUCTS = {
    "p-1": catalog_pb2.Product(product_id="p-1", name="Наушники", price_kopecks=1_999_90, stock=5),
    "p-2": catalog_pb2.Product(product_id="p-2", name="Книга", price_kopecks=500_00, stock=0),
}


@dataclass
class Seen:
    """Что увидел catalog: metadata и остаток deadline последнего вызова, резервы."""

    metadata: dict[str, str] = field(default_factory=dict)
    time_remaining: float | None = None
    reserved: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    released: list[str] = field(default_factory=list)
    # Задержка ReserveStock в секундах и «catalog сломан»
    delay: float = 0.0
    down: bool = False


SEEN = Seen()


def _remember(context: Context) -> None:
    SEEN.metadata = {
        key: value for key, value in context.invocation_metadata() or () if isinstance(value, str)
    }
    SEEN.time_remaining = context.time_remaining()
    if SEEN.down:
        raise DependencyUnavailable("postgres")


async def get_product(
    request: catalog_pb2.GetProductRequest, context: Context
) -> catalog_pb2.GetProductResponse:
    _remember(context)
    product = PRODUCTS.get(request.product_id)
    if product is None:
        raise NotFound("product", request.product_id)
    return catalog_pb2.GetProductResponse(product=product)


async def reserve_stock(
    request: catalog_pb2.ReserveStockRequest, context: Context
) -> catalog_pb2.ReserveStockResponse:
    _remember(context)
    await asyncio.sleep(SEEN.delay)
    violations = [
        PreconditionViolation(
            "INSUFFICIENT_STOCK",
            f"product:{item.product_id}",
            f"requested {item.quantity}, available {PRODUCTS[item.product_id].stock}",
        )
        if item.product_id in PRODUCTS
        else PreconditionViolation(
            "PRODUCT_NOT_FOUND", f"product:{item.product_id}", "product does not exist"
        )
        for item in request.items
        if item.product_id not in PRODUCTS or PRODUCTS[item.product_id].stock < item.quantity
    ]
    if violations:
        raise FailedPrecondition(violations, message="Not enough stock")
    SEEN.reserved[request.order_id] = [(item.product_id, item.quantity) for item in request.items]
    return catalog_pb2.ReserveStockResponse(order_id=request.order_id, items=request.items)


async def release_stock(
    request: catalog_pb2.ReleaseStockRequest, context: Context
) -> catalog_pb2.ReleaseStockResponse:
    _remember(context)
    SEEN.released.append(request.order_id)
    released = SEEN.reserved.pop(request.order_id, None) is not None
    return catalog_pb2.ReleaseStockResponse(order_id=request.order_id, released=released)


HANDLERS = {
    MethodSignature("GetProduct", "CatalogService", "catalog.v1"): annotate(get_product),
    MethodSignature("ReserveStock", "StockService", "catalog.v1"): annotate(reserve_stock),
    MethodSignature("ReleaseStock", "StockService", "catalog.v1"): annotate(release_stock),
}


@asynccontextmanager
async def fake_catalog() -> AsyncIterator[tuple[RunningServer, Seen]]:
    """Сервер и свежий `Seen`, который видят хэндлеры."""
    global SEEN
    SEEN = Seen()
    async with grpc_server(
        HANDLERS, [ExceptionHandlingInterceptor()], port=0, host="localhost", grace=0
    ) as server:
        yield server, SEEN
