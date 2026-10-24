from orders.v1 import orders_pb2
from stand_core import Context, rpc
from stand_core.grpc import current_user

from order_service.cart_view import cart_pb
from order_service.carts import Carts
from order_service.catalog_client import CatalogClient


@rpc("GetCart", package="orders.v1", service="OrderService")
async def get_cart(
    request: orders_pb2.GetCartRequest,
    context: Context,
    carts: Carts,
    catalog: CatalogClient,
) -> orders_pb2.GetCartResponse:
    return orders_pb2.GetCartResponse(cart=await cart_pb(current_user().id, carts, catalog))
