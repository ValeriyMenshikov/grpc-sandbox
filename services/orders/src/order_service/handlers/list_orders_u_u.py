from orders.v1 import orders_pb2
from stand_core import Context, rpc
from stand_core.grpc import FieldViolation, InvalidArgument, current_user

from order_service.convert import STATUS_FROM_PROTO, order_pb
from order_service.models import OrderStatus
from order_service.pagination import decode_page_token, encode_page_token, page_size
from order_service.repository import OrderRepository


def status_filter(request: orders_pb2.ListOrdersRequest) -> OrderStatus | None:
    """Фильтр по статусу; не задан или UNSPECIFIED — все статусы."""
    if not request.HasField("status") or request.status == orders_pb2.ORDER_STATUS_UNSPECIFIED:
        return None
    status = STATUS_FROM_PROTO.get(request.status)
    if status is None:
        raise InvalidArgument([FieldViolation("status", f"unknown status {request.status}")])
    return status


@rpc("ListOrders", package="orders.v1", service="OrderService")
async def list_orders(
    request: orders_pb2.ListOrdersRequest,
    context: Context,
    repository: OrderRepository,
) -> orders_pb2.ListOrdersResponse:
    status = status_filter(request)
    limit = page_size(request.pagination.page_size)
    offset = decode_page_token(request.pagination.page_token)
    # На одну запись больше лимита — признак следующей страницы
    orders = await repository.list_orders(current_user().id, status, offset, limit + 1)
    return orders_pb2.ListOrdersResponse(
        orders=[order_pb(order) for order in orders[:limit]],
        next_page_token=encode_page_token(offset + limit) if len(orders) > limit else "",
    )
