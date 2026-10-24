from collections.abc import AsyncIterator

from orders.v1 import orders_pb2
from stand_core import Context, rpc

from order_service.convert import STATUS_TO_PROTO, timestamp
from order_service.events import OrderEvents
from order_service.handlers.get_order_u_u import own_order
from order_service.models import FINAL_STATUSES, StatusChange
from order_service.repository import OrderRepository

# Без событий столько секунд — перечитать статус из Postgres (публикация в Redis могла не пройти)
RESYNC_INTERVAL_S = 10.0


def track_pb(change: StatusChange) -> orders_pb2.TrackOrderResponse:
    return orders_pb2.TrackOrderResponse(
        order_id=change.order_id,
        status=STATUS_TO_PROTO[change.status],
        changed_at=timestamp(change.changed_at),
    )


async def current_status(repository: OrderRepository, order_id: str) -> StatusChange:
    order = await own_order(repository, order_id)
    return StatusChange(order.order_id, order.status, order.updated_at)


@rpc("TrackOrder", package="orders.v1", service="OrderService")
async def track_order(
    request: orders_pb2.TrackOrderRequest,
    context: Context,
    repository: OrderRepository,
    events: OrderEvents,
) -> AsyncIterator[orders_pb2.TrackOrderResponse]:
    """Текущий статус, затем каждая смена; x-items-count выставляет StreamCountInterceptor."""
    # Ownership до подписки: чужой заказ — NOT_FOUND без похода в Redis
    order_id = (await current_status(repository, request.order_id)).order_id
    # Сначала подписка, потом статус из Postgres: смена между ними придёт событием
    async with events.subscribe(order_id) as subscription:
        last = await current_status(repository, order_id)
        yield track_pb(last)
        while last.status not in FINAL_STATUSES:
            change = await subscription.next(RESYNC_INTERVAL_S)
            if change is None:
                change = await current_status(repository, order_id)
            # Событие, уже учтённое в прочитанном статусе, и повтор после перечитывания — пропускаем
            if change.changed_at <= last.changed_at:
                continue
            last = change
            yield track_pb(last)
