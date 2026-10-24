from orders.v1 import orders_pb2
from stand_core import Context, rpc
from stand_core.grpc import FieldViolation, InvalidArgument, NotFound, current_user

from order_service.convert import order_pb
from order_service.models import Order
from order_service.repository import OrderRepository


async def own_order(repository: OrderRepository, order_id: str) -> Order:
    """Заказ текущего пользователя; чужой и несуществующий неразличимы — NOT_FOUND."""
    if not order_id:
        raise InvalidArgument([FieldViolation("order_id", "must not be empty")])
    order = await repository.get_order(order_id)
    if order is None or order.user_id != current_user().id:
        raise NotFound("order", order_id)
    return order


@rpc("GetOrder", package="orders.v1", service="OrderService")
async def get_order(
    request: orders_pb2.GetOrderRequest,
    context: Context,
    repository: OrderRepository,
) -> orders_pb2.GetOrderResponse:
    return orders_pb2.GetOrderResponse(
        order=order_pb(await own_order(repository, request.order_id))
    )
