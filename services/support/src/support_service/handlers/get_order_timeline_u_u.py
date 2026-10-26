from stand_core import Context, rpc
from stand_core.grpc import FieldViolation, InvalidArgument
from support.v1 import support_pb2

from support_service.convert import order_event_pb
from support_service.repository import ChatRepository


@rpc("GetOrderTimeline", package="support.v1", service="SupportService")
async def get_order_timeline(
    request: support_pb2.GetOrderTimelineRequest,
    context: Context,
    repository: ChatRepository,
) -> support_pb2.GetOrderTimelineResponse:
    """Проекция смен статуса заказа, старые первыми; о заказе событий нет — пустой список.

    support не ходит в order-service: отдаёт то, что успел прочитать из очереди.
    """
    if not request.order_id:
        raise InvalidArgument([FieldViolation("order_id", "must not be empty")])
    events = await repository.order_events(request.order_id)
    return support_pb2.GetOrderTimelineResponse(events=[order_event_pb(event) for event in events])
