"""Клиент к StockService: резерв и снятие резерва под заказ."""

from collections.abc import Mapping

import grpc
from catalog.v1 import catalog_pb2
from stand_core.clients import GrpcClient
from stand_core.grpc import DependencyUnavailable, FailedPrecondition, precondition_violations
from stand_core.logging import get_logger

logger = get_logger(__name__)

RESERVE_STOCK = "/catalog.v1.StockService/ReserveStock"
RELEASE_STOCK = "/catalog.v1.StockService/ReleaseStock"
# Снятие резерва после неудачного Checkout: deadline входящего вызова к этому моменту уже может
# истечь, поэтому у вызова свой короткий deadline
RELEASE_QUIETLY_DEADLINE_S = 1.0


class StockClient(GrpcClient):
    address_env = "CATALOG_ADDR"
    dependency = "catalog"

    async def reserve(self, order_id: str, items: Mapping[str, int]) -> None:
        """Резерв всех позиций под order_id (идемпотентно в catalog).

        Нехватка → `FailedPrecondition` с нарушениями из details catalog-service; catalog
        недоступен или не ответил в срок → `DependencyUnavailable`.
        """
        request = catalog_pb2.ReserveStockRequest(
            order_id=order_id,
            items=[
                catalog_pb2.StockItem(product_id=product_id, quantity=quantity)
                for product_id, quantity in items.items()
            ],
        )
        try:
            await self.unary(RESERVE_STOCK, request, catalog_pb2.ReserveStockResponse)
        except grpc.aio.AioRpcError as exc:
            if exc.code() is grpc.StatusCode.FAILED_PRECONDITION:
                raise FailedPrecondition(
                    precondition_violations(exc), message=exc.details() or None
                ) from exc
            raise

    async def release(self, order_id: str, *, deadline: float | None = None) -> bool:
        """Снять резерв; False — резерва уже не было."""
        response = await self.unary(
            RELEASE_STOCK,
            catalog_pb2.ReleaseStockRequest(order_id=order_id),
            catalog_pb2.ReleaseStockResponse,
            deadline=deadline,
        )
        return response.released

    async def release_quietly(self, order_id: str) -> None:
        """Снять резерв, если он мог остаться после неудачи; ошибки только в лог."""
        try:
            await self.release(order_id, deadline=RELEASE_QUIETLY_DEADLINE_S)
        except (DependencyUnavailable, grpc.aio.AioRpcError) as exc:
            logger.warning("orders.release_failed", order_id=order_id, error=str(exc))
