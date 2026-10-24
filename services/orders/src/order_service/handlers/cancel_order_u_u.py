from orders.v1 import orders_pb2
from stand_core import Context, rpc
from stand_core.grpc import FailedPrecondition, PreconditionViolation

from order_service.convert import order_pb
from order_service.handlers.get_order_u_u import own_order
from order_service.models import OrderStatus
from order_service.repository import OrderRepository
from order_service.stock_client import StockClient


@rpc("CancelOrder", package="orders.v1", service="OrderService")
async def cancel_order(
    request: orders_pb2.CancelOrderRequest,
    context: Context,
    repository: OrderRepository,
    stock: StockClient,
) -> orders_pb2.CancelOrderResponse:
    order = await own_order(repository, request.order_id)
    # Повторная отмена снова снимает резерв: так повтор после UNAVAILABLE от catalog доводит
    # отмену до конца (ReleaseStock идемпотентен)
    if order.status is not OrderStatus.CANCELLED:
        cancelled = await repository.cancel(order.order_id)
        if cancelled is None:
            current = await repository.get_order(order.order_id)
            status = (current or order).status
            raise FailedPrecondition(
                [
                    PreconditionViolation(
                        "ORDER_NOT_CANCELLABLE",
                        f"order:{order.order_id}",
                        f"order in status {status} cannot be cancelled",
                    )
                ],
                message="Order can be cancelled only before it is handed to courier",
            )
        order = cancelled
    await stock.release(order.order_id)
    return orders_pb2.CancelOrderResponse(order=order_pb(order))
