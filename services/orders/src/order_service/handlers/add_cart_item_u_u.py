from orders.v1 import orders_pb2
from stand_core import Context, rpc
from stand_core.grpc import FieldViolation, InvalidArgument, NotFound, current_user

from order_service.cart_view import cart_pb
from order_service.carts import MAX_CART_QUANTITY, Carts
from order_service.catalog_client import CatalogClient


@rpc("AddCartItem", package="orders.v1", service="OrderService")
async def add_cart_item(
    request: orders_pb2.AddCartItemRequest,
    context: Context,
    carts: Carts,
    catalog: CatalogClient,
) -> orders_pb2.AddCartItemResponse:
    violations = []
    if not request.product_id:
        violations.append(FieldViolation("product_id", "must not be empty"))
    if request.quantity <= 0:
        violations.append(FieldViolation("quantity", "must be positive"))
    elif request.quantity > MAX_CART_QUANTITY:
        violations.append(FieldViolation("quantity", f"must be at most {MAX_CART_QUANTITY}"))
    if violations:
        raise InvalidArgument(violations)
    # Остаток не проверяем: корзина — намерение, остатки сверяет резерв в Checkout
    if await catalog.get_product(request.product_id) is None:
        raise NotFound("product", request.product_id)
    user_id = current_user().id
    if not await carts.add(user_id, request.product_id, request.quantity):
        raise InvalidArgument(
            [FieldViolation("quantity", f"cart quantity must be at most {MAX_CART_QUANTITY}")]
        )
    return orders_pb2.AddCartItemResponse(cart=await cart_pb(user_id, carts, catalog))
