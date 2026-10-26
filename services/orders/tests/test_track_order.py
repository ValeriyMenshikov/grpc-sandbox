"""TrackOrder напрямую: текущий статус первым, смены из pub/sub, закрытие на финальном статусе."""

from datetime import UTC, timedelta
from unittest.mock import Mock

import pytest
from order_service.domain_events import DomainEvents
from order_service.fulfillment import Fulfillment
from order_service.handlers import track_order_u_s
from order_service.handlers.track_order_u_s import track_order
from order_service.models import OrderStatus, StatusChange
from order_service.settings import OrderSettings
from orders.v1 import orders_pb2
from stand_core.grpc import InvalidArgument, NotFound

from .fakes import OTHER_ID, FakeEvents, FakeRepository

pytestmark = pytest.mark.usefixtures("buyer")

DELIVERY = [
    orders_pb2.ORDER_STATUS_PAID,
    orders_pb2.ORDER_STATUS_ASSEMBLING,
    orders_pb2.ORDER_STATUS_HANDED_TO_COURIER,
    orders_pb2.ORDER_STATUS_DELIVERED,
]


@pytest.fixture
def fulfillment(
    repository: FakeRepository, events: FakeEvents, domain: DomainEvents
) -> Fulfillment:
    return Fulfillment(repository, events, OrderSettings(), domain)


def request(order_id: str) -> orders_pb2.TrackOrderRequest:
    return orders_pb2.TrackOrderRequest(order_id=order_id)


async def test_current_status_first_then_changes_until_delivered(
    context: Mock, repository: FakeRepository, events: FakeEvents, fulfillment: Fulfillment
) -> None:
    order = repository.add()
    stream = track_order(request(order.order_id), context, repository, events)

    first = await anext(stream)
    for _ in DELIVERY:
        await fulfillment.advance()
    rest = [message async for message in stream]

    assert first.order_id == order.order_id
    assert first.status == orders_pb2.ORDER_STATUS_CREATED
    assert first.changed_at.ToDatetime(tzinfo=UTC) == order.updated_at
    assert [message.status for message in rest] == DELIVERY
    changed_at = [message.changed_at.ToNanoseconds() for message in [first, *rest]]
    assert changed_at == sorted(set(changed_at))
    # Стрим закрылся — подписка снята
    assert events.subscribers[order.order_id] == []


async def test_change_between_subscribe_and_read_is_not_lost_or_doubled(
    context: Mock, repository: FakeRepository, events: FakeEvents, fulfillment: Fulfillment
) -> None:
    order = repository.add()
    # Смена статуса прямо после подписки: она и в БД, и в очереди подписки
    events.on_subscribe = lambda _: fulfillment.advance()
    stream = track_order(request(order.order_id), context, repository, events)

    first = await anext(stream)
    events.on_subscribe = None
    for _ in DELIVERY[1:]:
        await fulfillment.advance()
    rest = [message async for message in stream]

    assert first.status == orders_pb2.ORDER_STATUS_PAID
    assert [message.status for message in rest] == DELIVERY[1:]


@pytest.mark.parametrize("status", [OrderStatus.DELIVERED, OrderStatus.CANCELLED])
async def test_final_status_closes_after_first_message(
    context: Mock, repository: FakeRepository, events: FakeEvents, status: OrderStatus
) -> None:
    order = repository.add(status=status)

    messages = [m async for m in track_order(request(order.order_id), context, repository, events)]

    assert len(messages) == 1
    assert messages[0].status == orders_pb2.OrderStatus.Value(f"ORDER_STATUS_{status.value}")


async def test_cancel_event_closes_stream(
    context: Mock, repository: FakeRepository, events: FakeEvents
) -> None:
    order = repository.add(status=OrderStatus.ASSEMBLING)
    stream = track_order(request(order.order_id), context, repository, events)

    await anext(stream)
    cancelled = await repository.cancel(order.order_id)
    assert cancelled is not None
    await events.publish_quietly(
        StatusChange(cancelled.order_id, cancelled.status, cancelled.updated_at)
    )
    rest = [message async for message in stream]

    assert [message.status for message in rest] == [orders_pb2.ORDER_STATUS_CANCELLED]


async def test_lost_event_is_recovered_by_resync(
    context: Mock,
    repository: FakeRepository,
    events: FakeEvents,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(track_order_u_s, "RESYNC_INTERVAL_S", 0.01)
    order = repository.add(status=OrderStatus.HANDED_TO_COURIER)
    stream = track_order(request(order.order_id), context, repository, events)

    await anext(stream)
    # Статус сменился, а публикация в Redis не дошла
    await repository.advance_due(timedelta(0))
    rest = [message async for message in stream]

    assert [message.status for message in rest] == [orders_pb2.ORDER_STATUS_DELIVERED]


async def test_foreign_and_missing_orders_are_not_found(
    context: Mock, repository: FakeRepository, events: FakeEvents
) -> None:
    foreign = repository.add(user_id=OTHER_ID)

    for order_id in (foreign.order_id, "missing"):
        with pytest.raises(NotFound):
            await anext(track_order(request(order_id), context, repository, events))
    assert events.subscribers == {}


async def test_empty_order_id_is_invalid_argument(
    context: Mock, repository: FakeRepository, events: FakeEvents
) -> None:
    with pytest.raises(InvalidArgument):
        await anext(track_order(request(""), context, repository, events))
