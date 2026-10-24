from orders.v1 import orders_pb2
from stand_core import Context, rpc
from stand_core.grpc import FieldViolation, InvalidArgument, NotFound, current_user

from order_service.cart_view import cart_pb
from order_service.carts import Carts
from order_service.catalog_client import CatalogClient


@rpc("RemoveCartItem", package="orders.v1", service="OrderService")
async def remove_cart_item(
    request: orders_pb2.RemoveCartItemRequest,
    context: Context,
    carts: Carts,
    catalog: CatalogClient,
) -> orders_pb2.RemoveCartItemResponse:
    if not request.product_id:
        raise InvalidArgument([FieldViolation("product_id", "must not be empty")])
    user_id = current_user().id
    if not await carts.remove(user_id, request.product_id):
        raise NotFound("cart_item", request.product_id)
    return orders_pb2.RemoveCartItemResponse(cart=await cart_pb(user_id, carts, catalog))
