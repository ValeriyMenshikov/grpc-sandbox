"""Оформление и просмотр заказов: эндпоинты поверх order-service."""

from typing import Annotated

from common.v1 import money_pb2
from fastapi import Header
from nuke_di.fastapi import ClientRouter
from orders.v1 import orders_pb2

from gateway import schemas
from gateway.clients import OrdersClient
from gateway.params import PageSize, PageToken

router = ClientRouter(tags=["orders"])


@router.post("/checkout")
async def checkout(
    orders: OrdersClient,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> schemas.Order:
    """Заголовок `Idempotency-Key` уходит в metadata `idempotency-key` как есть."""
    response = await orders.checkout(idempotency_key)
    return schemas.order(response.order)


@router.get("/orders")
async def list_orders(
    orders: OrdersClient,
    status: schemas.OrderStatus | None = None,
    page_size: PageSize = 0,
    page_token: PageToken = "",
) -> schemas.OrdersPage:
    request = orders_pb2.ListOrdersRequest(
        pagination=money_pb2.Pagination(page_size=page_size, page_token=page_token)
    )
    if status is not None:
        request.status = orders_pb2.OrderStatus.Value(f"ORDER_STATUS_{status}")
    return schemas.orders_page(await orders.list_orders(request))


@router.get("/orders/{order_id}")
async def get_order(order_id: str, orders: OrdersClient) -> schemas.OrderDetail:
    return schemas.order_detail(await orders.get_order(order_id))
