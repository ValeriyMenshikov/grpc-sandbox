"""Корзина: эндпоинты поверх order-service."""

from nuke_di.fastapi import ClientRouter

from gateway import schemas
from gateway.clients import OrdersClient

router = ClientRouter(tags=["cart"])


@router.get("/cart")
async def get_cart(orders: OrdersClient) -> schemas.Cart:
    response = await orders.get_cart()
    return schemas.cart(response.cart)


@router.post("/cart/items")
async def add_cart_item(body: schemas.AddCartItemIn, orders: OrdersClient) -> schemas.Cart:
    response = await orders.add_cart_item(body.product_id, body.quantity)
    return schemas.cart(response.cart)


@router.delete("/cart/items/{product_id}")
async def remove_cart_item(product_id: str, orders: OrdersClient) -> schemas.Cart:
    response = await orders.remove_cart_item(product_id)
    return schemas.cart(response.cart)
