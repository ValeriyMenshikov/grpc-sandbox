from orders.v1 import orders_pb2
from stand_core import Context, rpc
from stand_core.grpc import FieldViolation, InvalidArgument, NotFound, current_user

from order_service.convert import STATUS_TO_PROTO, order_pb, status_change_pb
from order_service.models import DELIVERY_STEPS, Order
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
    order = await own_order(repository, request.order_id)
    history = await repository.status_history(order.order_id)
    return orders_pb2.GetOrderResponse(
        order=order_pb(order),
        history=[status_change_pb(change) for change in history],
        delivery_steps=[STATUS_TO_PROTO[step] for step in DELIVERY_STEPS],
    )
