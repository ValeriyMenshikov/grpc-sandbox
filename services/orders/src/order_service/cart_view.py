"""Корзина для ответа: позиции из Redis + актуальные название, цена и остаток из catalog."""

from orders.v1 import orders_pb2
from stand_core.logging import get_logger

from order_service.carts import Carts
from order_service.catalog_client import CatalogClient
from order_service.convert import money

logger = get_logger(__name__)


async def cart_pb(user_id: str, carts: Carts, catalog: CatalogClient) -> orders_pb2.Cart:
    """Корзина пользователя; товары, которых уже нет в catalog, в ответ не попадают."""
    items = await carts.items(user_id)
    products = await catalog.get_products(items)
    cart = orders_pb2.Cart()
    total = 0
    for product_id, quantity in items.items():
        product = products.get(product_id)
        if product is None:
            logger.warning("orders.cart_product_missing", user_id=user_id, product_id=product_id)
            continue
        total += product.price_kopecks * quantity
        cart.items.append(
            orders_pb2.CartItem(
                product_id=product_id,
                name=product.name,
                quantity=quantity,
                unit_price=money(product.price_kopecks),
                available=product.stock,
            )
        )
    cart.total.CopyFrom(money(total))
    return cart
