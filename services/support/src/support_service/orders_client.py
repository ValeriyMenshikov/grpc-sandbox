"""Клиент к OrderService от имени пользователя: заказ и его статус для чата."""

import grpc
from orders.v1 import orders_pb2
from stand_core.clients import GrpcClient

GET_ORDER = "/orders.v1.OrderService/GetOrder"


class OrdersClient(GrpcClient):
    address_env = "ORDERS_ADDR"
    dependency = "orders"

    def timeout(self) -> float:
        # Chat живёт долго: остаток его deadline — не срок для одного GetOrder
        return min(super().timeout(), self._settings.grpc_default_deadline_seconds)

    async def get_order(self, order_id: str) -> orders_pb2.Order | None:
        """Заказ текущего пользователя; None — заказа нет или он чужой (NOT_FOUND соседа).

        Идёт с `authorization` пользователя: order-service сам проверяет владельца.
        """
        try:
            response = await self.unary(
                GET_ORDER,
                orders_pb2.GetOrderRequest(order_id=order_id),
                orders_pb2.GetOrderResponse,
                forward_authorization=True,
            )
        except grpc.aio.AioRpcError as exc:
            if exc.code() is grpc.StatusCode.NOT_FOUND:
                return None
            raise
        return response.order
