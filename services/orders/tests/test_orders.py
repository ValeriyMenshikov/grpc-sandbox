from unittest.mock import Mock

import pytest
from common.v1 import money_pb2
from order_service.domain_events import DomainEvents
from order_service.handlers.cancel_order_u_u import cancel_order
from order_service.handlers.get_order_u_u import get_order
from order_service.handlers.list_orders_u_u import list_orders
from order_service.models import OrderStatus
from orders.v1 import orders_pb2
from stand_core.events import ORDER_STATUS_CHANGED, parse_order_status_changed
from stand_core.grpc import (
    DependencyUnavailable,
    FailedPrecondition,
    InvalidArgument,
    NotFound,
)

from .fakes import BUYER_ID, OTHER_ID, FakeEvents, FakeRabbit, FakeRepository, FakeStock

pytestmark = pytest.mark.usefixtures("buyer")


async def test_get_own_order(context: Mock, repository: FakeRepository) -> None:
    order = repository.add()

    response = await get_order(
        orders_pb2.GetOrderRequest(order_id=order.order_id), context, repository
    )

    assert response.order.order_id == order.order_id
    assert response.order.status == orders_pb2.ORDER_STATUS_CREATED
    assert response.order.total.units == 100


@pytest.mark.parametrize("owner", [OTHER_ID, None])
async def test_foreign_and_missing_order_are_not_found(
    context: Mock, repository: FakeRepository, owner: str | None
) -> None:
    order_id = "missing" if owner is None else repository.add(user_id=owner).order_id

    with pytest.raises(NotFound) as info:
        await get_order(orders_pb2.GetOrderRequest(order_id=order_id), context, repository)

    assert (info.value.resource_type, info.value.resource_name) == ("order", order_id)


async def test_get_order_requires_id(context: Mock, repository: FakeRepository) -> None:
    with pytest.raises(InvalidArgument):
        await get_order(orders_pb2.GetOrderRequest(), context, repository)


async def test_list_newest_first_with_pages(context: Mock, repository: FakeRepository) -> None:
    ids = [repository.add().order_id for _ in range(5)]
    repository.add(user_id=OTHER_ID)
    pagination = orders_pb2.ListOrdersRequest(pagination=money_pb2.Pagination(page_size=2))

    pages = []
    while True:
        response = await list_orders(pagination, context, repository)
        pages.append([order.order_id for order in response.orders])
        if not response.next_page_token:
            break
        pagination.pagination.page_token = response.next_page_token

    assert pages == [ids[4:2:-1], ids[2:0:-1], ids[:1]]


async def test_list_filters_by_status(context: Mock, repository: FakeRepository) -> None:
    repository.add()
    cancelled = repository.add(status=OrderStatus.CANCELLED)

    filtered = await list_orders(
        orders_pb2.ListOrdersRequest(status=orders_pb2.ORDER_STATUS_CANCELLED), context, repository
    )
    unspecified = await list_orders(
        orders_pb2.ListOrdersRequest(status=orders_pb2.ORDER_STATUS_UNSPECIFIED),
        context,
        repository,
    )

    assert [order.order_id for order in filtered.orders] == [cancelled.order_id]
    assert len(unspecified.orders) == 2


@pytest.mark.parametrize(
    ("request_", "field"),
    [
        (
            orders_pb2.ListOrdersRequest(pagination=money_pb2.Pagination(page_token="bad")),
            "pagination.page_token",
        ),
        (
            orders_pb2.ListOrdersRequest(pagination=money_pb2.Pagination(page_size=-1)),
            "pagination.page_size",
        ),
        (orders_pb2.ListOrdersRequest(status=orders_pb2.OrderStatus.ValueType(99)), "status"),
    ],
)
async def test_list_validation(
    context: Mock, repository: FakeRepository, request_: orders_pb2.ListOrdersRequest, field: str
) -> None:
    with pytest.raises(InvalidArgument) as info:
        await list_orders(request_, context, repository)

    assert [v.field for v in info.value.field_violations] == [field]


@pytest.mark.parametrize("status", [OrderStatus.CREATED, OrderStatus.PAID, OrderStatus.ASSEMBLING])
async def test_cancel_before_courier_releases_stock(
    context: Mock,
    repository: FakeRepository,
    stock: FakeStock,
    events: FakeEvents,
    domain: DomainEvents,
    rabbit: FakeRabbit,
    status: OrderStatus,
) -> None:
    order = repository.add(status=status)

    response = await cancel_order(
        orders_pb2.CancelOrderRequest(order_id=order.order_id),
        context,
        repository,
        stock,
        events,
        domain,
    )

    assert response.order.status == orders_pb2.ORDER_STATUS_CANCELLED
    assert repository.orders[order.order_id].status is OrderStatus.CANCELLED
    assert stock.released == [order.order_id]
    # TrackOrder узнаёт об отмене из Redis и закрывается
    [published] = events.published
    assert (published.order_id, published.status) == (order.order_id, OrderStatus.CANCELLED)
    assert published.changed_at == repository.orders[order.order_id].updated_at
    # Доменное событие order.status_changed — в RabbitMQ
    [(routing_key, payload)] = rabbit.published
    event = parse_order_status_changed(payload)
    assert routing_key == ORDER_STATUS_CHANGED
    assert (event.order_id, event.user_id, event.status) == (order.order_id, BUYER_ID, "CANCELLED")
    assert event.changed_at == published.changed_at


@pytest.mark.parametrize("status", [OrderStatus.HANDED_TO_COURIER, OrderStatus.DELIVERED])
async def test_cancel_after_courier_is_failed_precondition(
    context: Mock,
    repository: FakeRepository,
    stock: FakeStock,
    events: FakeEvents,
    domain: DomainEvents,
    rabbit: FakeRabbit,
    status: OrderStatus,
) -> None:
    order = repository.add(status=status)

    with pytest.raises(FailedPrecondition) as info:
        await cancel_order(
            orders_pb2.CancelOrderRequest(order_id=order.order_id),
            context,
            repository,
            stock,
            events,
            domain,
        )

    [violation] = info.value.violations
    assert (violation.type, violation.subject) == (
        "ORDER_NOT_CANCELLABLE",
        f"order:{order.order_id}",
    )
    assert status.value in violation.description
    assert repository.orders[order.order_id].status is status
    assert stock.released == []
    assert events.published == []
    assert rabbit.published == []


async def test_cancel_foreign_order_is_not_found(
    context: Mock,
    repository: FakeRepository,
    stock: FakeStock,
    events: FakeEvents,
    domain: DomainEvents,
) -> None:
    order = repository.add(user_id=OTHER_ID)

    with pytest.raises(NotFound):
        await cancel_order(
            orders_pb2.CancelOrderRequest(order_id=order.order_id),
            context,
            repository,
            stock,
            events,
            domain,
        )
    assert repository.orders[order.order_id].status is OrderStatus.CREATED


async def test_repeat_cancel_finishes_release_after_catalog_outage(
    context: Mock,
    repository: FakeRepository,
    stock: FakeStock,
    events: FakeEvents,
    domain: DomainEvents,
) -> None:
    order = repository.add()
    request = orders_pb2.CancelOrderRequest(order_id=order.order_id)
    stock.error = DependencyUnavailable("catalog")
    with pytest.raises(DependencyUnavailable):
        await cancel_order(request, context, repository, stock, events, domain)
    stock.error = None

    response = await cancel_order(request, context, repository, stock, events, domain)

    assert response.order.status == orders_pb2.ORDER_STATUS_CANCELLED
    assert stock.released == [order.order_id]
