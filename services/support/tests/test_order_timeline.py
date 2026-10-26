"""GetOrderTimeline напрямую: проекция старые первыми, неизвестный заказ — пусто."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from stand_core.grpc import InvalidArgument
from support.v1 import support_pb2
from support_service.handlers.get_order_timeline_u_u import get_order_timeline
from support_service.models import OrderEvent

from .fakes import FakeRepository

CREATED_AT = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


async def test_returns_projection_oldest_first(context: Mock, repository: FakeRepository) -> None:
    await repository.record_order_event(OrderEvent("o-1", "PAID", CREATED_AT + timedelta(1)))
    await repository.record_order_event(OrderEvent("o-1", "CREATED", CREATED_AT))

    response = await get_order_timeline(
        support_pb2.GetOrderTimelineRequest(order_id="o-1"), context, repository
    )

    assert [event.status for event in response.events] == [
        support_pb2.ORDER_STATUS_CREATED,
        support_pb2.ORDER_STATUS_PAID,
    ]
    assert response.events[0].changed_at.ToDatetime(tzinfo=UTC) == CREATED_AT


async def test_unknown_order_is_empty(context: Mock, repository: FakeRepository) -> None:
    response = await get_order_timeline(
        support_pb2.GetOrderTimelineRequest(order_id="missing"), context, repository
    )

    assert list(response.events) == []


async def test_empty_order_id_is_invalid(context: Mock, repository: FakeRepository) -> None:
    with pytest.raises(InvalidArgument):
        await get_order_timeline(support_pb2.GetOrderTimelineRequest(), context, repository)
