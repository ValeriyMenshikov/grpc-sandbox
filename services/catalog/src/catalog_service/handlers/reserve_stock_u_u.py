import asyncio

import grpc
from catalog.v1 import catalog_pb2
from stand_core import Context, rpc
from stand_core.grpc import (
    FailedPrecondition,
    FieldViolation,
    InvalidArgument,
    PreconditionViolation,
    metadata_value,
)

from catalog_service.models import StockItem, StockShortage
from catalog_service.repository import CatalogRepository
from catalog_service.settings import CatalogSettings

DEBUG_DELAY_HEADER = "x-debug-delay-ms"


def reserve_delay_ms(context: Context, settings: CatalogSettings) -> int:
    """Задержка вызова: metadata x-debug-delay-ms, иначе env STOCK_RESERVE_DELAY_MS."""
    raw = metadata_value(context, DEBUG_DELAY_HEADER)
    if raw is None:
        return settings.stock_reserve_delay_ms
    try:
        delay = int(raw)
    except ValueError:
        delay = -1
    if delay < 0:
        raise InvalidArgument(
            [FieldViolation(DEBUG_DELAY_HEADER, "must be a non-negative integer")]
        )
    return delay


async def sleep_within_deadline(context: Context, delay_ms: int) -> None:
    """Подождать delay_ms, но не дольше deadline вызова.

    Если deadline наступил раньше, вызов завершается DEADLINE_EXCEEDED и резерв не делается:
    клиент уже получил ошибку и не узнает о резерве.
    """
    if delay_ms <= 0:
        return
    delay = delay_ms / 1000
    remaining = context.time_remaining()
    if remaining is None or remaining >= delay:
        await asyncio.sleep(delay)
        return
    await asyncio.sleep(remaining)
    await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "Deadline exceeded during delay")


def _items(request: catalog_pb2.ReserveStockRequest) -> list[StockItem]:
    violations = []
    if not request.order_id:
        violations.append(FieldViolation("order_id", "must not be empty"))
    if not request.items:
        violations.append(FieldViolation("items", "must not be empty"))
    seen: set[str] = set()
    for index, item in enumerate(request.items):
        if not item.product_id:
            violations.append(FieldViolation(f"items[{index}].product_id", "must not be empty"))
        elif item.product_id in seen:
            violations.append(FieldViolation(f"items[{index}].product_id", "duplicate product"))
        seen.add(item.product_id)
        if item.quantity <= 0:
            violations.append(FieldViolation(f"items[{index}].quantity", "must be positive"))
    if violations:
        raise InvalidArgument(violations)
    return [StockItem(item.product_id, item.quantity) for item in request.items]


def _violation(shortage: StockShortage) -> PreconditionViolation:
    subject = f"product:{shortage.product_id}"
    if shortage.available is None:
        return PreconditionViolation("PRODUCT_NOT_FOUND", subject, "product does not exist")
    return PreconditionViolation(
        "INSUFFICIENT_STOCK",
        subject,
        f"requested {shortage.requested}, available {shortage.available}",
    )


@rpc("ReserveStock", package="catalog.v1", service="StockService")
async def reserve_stock(
    request: catalog_pb2.ReserveStockRequest,
    context: Context,
    repository: CatalogRepository,
    settings: CatalogSettings,
) -> catalog_pb2.ReserveStockResponse:
    items = _items(request)
    await sleep_within_deadline(context, reserve_delay_ms(context, settings))
    result = await repository.reserve_stock(request.order_id, items)
    if result.shortages:
        raise FailedPrecondition(
            [_violation(shortage) for shortage in result.shortages],
            message="Not enough stock",
        )
    return catalog_pb2.ReserveStockResponse(
        order_id=request.order_id,
        items=[
            catalog_pb2.StockItem(product_id=item.product_id, quantity=item.quantity)
            for item in result.items
        ],
    )
