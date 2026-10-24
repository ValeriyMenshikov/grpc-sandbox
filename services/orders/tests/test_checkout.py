import asyncio
from collections.abc import Mapping
from unittest.mock import Mock

import pytest
from order_service.handlers.checkout_u_u import checkout
from order_service.idempotency import IdempotencyRecord
from order_service.models import OrderStatus
from order_service.settings import OrderSettings
from orders.v1 import orders_pb2
from stand_core.grpc import DependencyUnavailable, FailedPrecondition, InvalidArgument

from .conftest import IDEMPOTENCY_TTL_S
from .fakes import (
    BUYER_ID,
    FakeCarts,
    FakeCatalog,
    FakeIdempotency,
    FakeRepository,
    FakeStock,
)

pytestmark = pytest.mark.usefixtures("buyer")


class Checkout:
    """Вызов хэндлера Checkout с фейками из фикстур."""

    def __init__(
        self,
        carts: FakeCarts,
        idempotency: FakeIdempotency,
        repository: FakeRepository,
        stock: FakeStock,
        catalog: FakeCatalog,
        settings: OrderSettings,
    ) -> None:
        self.args = (carts, idempotency, repository, stock, catalog, settings)

    async def __call__(self, key: str | None = "key-1") -> orders_pb2.CheckoutResponse:
        context = Mock()
        context.invocation_metadata.return_value = (
            () if key is None else (("idempotency-key", key),)
        )
        return await checkout(orders_pb2.CheckoutRequest(), context, *self.args)


@pytest.fixture
def call(
    carts: FakeCarts,
    idempotency: FakeIdempotency,
    repository: FakeRepository,
    stock: FakeStock,
    catalog: FakeCatalog,
    settings: OrderSettings,
) -> Checkout:
    carts.carts[BUYER_ID] = {"p-1": 2, "p-2": 1}
    return Checkout(carts, idempotency, repository, stock, catalog, settings)


async def test_creates_order_reserves_stock_and_clears_cart(
    call: Checkout,
    carts: FakeCarts,
    idempotency: FakeIdempotency,
    repository: FakeRepository,
    stock: FakeStock,
) -> None:
    response = await call()

    order = response.order
    assert order.status == orders_pb2.ORDER_STATUS_CREATED
    assert order.user_id == BUYER_ID
    assert [(i.product_id, i.name, i.quantity) for i in order.items] == [
        ("p-1", "Наушники", 2),
        ("p-2", "Книга", 1),
    ]
    assert (order.total.units, order.total.nanos) == (4499, 800_000_000)
    assert stock.reserve_calls == [(order.order_id, {"p-1": 2, "p-2": 1})]
    assert repository.orders[order.order_id].status is OrderStatus.CREATED
    assert carts.carts == {}
    assert idempotency.records[BUYER_ID, "key-1"] == IdempotencyRecord(order.order_id, False)
    assert idempotency.ttls[BUYER_ID, "key-1"] == IDEMPOTENCY_TTL_S


async def test_same_key_returns_same_order_without_new_reserve(
    call: Checkout, carts: FakeCarts, repository: FakeRepository, stock: FakeStock
) -> None:
    first = await call()
    carts.carts[BUYER_ID] = {"p-1": 1}

    second = await call()

    assert second.order.order_id == first.order.order_id
    assert len(stock.reserve_calls) == 1
    assert len(repository.orders) == 1
    assert carts.carts[BUYER_ID] == {"p-1": 1}


async def test_new_key_creates_new_order(call: Checkout, carts: FakeCarts) -> None:
    first = await call("key-1")
    carts.carts[BUYER_ID] = {"p-1": 1}

    second = await call("key-2")

    assert second.order.order_id != first.order.order_id


async def test_keys_are_per_user(
    call: Checkout, idempotency: FakeIdempotency, repository: FakeRepository
) -> None:
    other = repository.add(user_id="u-other")
    idempotency.records["u-other", "key-1"] = IdempotencyRecord(other.order_id, False)

    response = await call("key-1")

    assert response.order.order_id != other.order_id


@pytest.mark.parametrize("key", [None, "", "   ", "k" * 129])
async def test_idempotency_key_is_required(
    call: Checkout, stock: FakeStock, key: str | None
) -> None:
    with pytest.raises(InvalidArgument) as info:
        await call(key)

    assert [v.field for v in info.value.field_violations] == ["idempotency-key"]
    assert stock.reserve_calls == []


async def test_empty_cart_is_failed_precondition(call: Checkout, carts: FakeCarts) -> None:
    carts.carts.clear()

    with pytest.raises(FailedPrecondition) as info:
        await call()

    assert [v.type for v in info.value.violations] == ["CART_EMPTY"]


async def test_shortage_passes_catalog_details_and_frees_key(
    call: Checkout,
    carts: FakeCarts,
    idempotency: FakeIdempotency,
    repository: FakeRepository,
    stock: FakeStock,
) -> None:
    stock.available["p-2"] = 0

    with pytest.raises(FailedPrecondition) as info:
        await call()

    assert [(v.type, v.subject) for v in info.value.violations] == [
        ("INSUFFICIENT_STOCK", "product:p-2")
    ]
    assert repository.orders == {}
    assert idempotency.records == {}
    assert carts.carts[BUYER_ID] == {"p-1": 2, "p-2": 1}
    assert stock.quietly_released == []


async def test_catalog_unavailable_creates_no_order(
    call: Checkout,
    carts: FakeCarts,
    idempotency: FakeIdempotency,
    repository: FakeRepository,
    stock: FakeStock,
) -> None:
    stock.error = DependencyUnavailable("catalog")

    with pytest.raises(DependencyUnavailable):
        await call()

    [(order_id, _)] = stock.reserve_calls
    assert repository.orders == {}
    assert idempotency.records == {}
    assert carts.carts[BUYER_ID] == {"p-1": 2, "p-2": 1}
    # Резерв мог состояться до таймаута — его пытаются снять
    assert stock.quietly_released == [order_id]


async def test_failure_keeps_key_taken_over_by_another_call(
    carts: FakeCarts,
    idempotency: FakeIdempotency,
    repository: FakeRepository,
    catalog: FakeCatalog,
    settings: OrderSettings,
) -> None:
    other = repository.add()

    class TakenOverStock(FakeStock):
        async def reserve(self, order_id: str, items: Mapping[str, int]) -> None:
            # Метка этого вызова истекла, ключ занял и закрепил за собой другой вызов
            idempotency.records[BUYER_ID, "key-1"] = IdempotencyRecord(other.order_id, False)
            raise DependencyUnavailable("catalog")

    carts.carts[BUYER_ID] = {"p-1": 1}
    call = Checkout(carts, idempotency, repository, TakenOverStock(), catalog, settings)

    with pytest.raises(DependencyUnavailable):
        await call()

    assert idempotency.records[BUYER_ID, "key-1"] == IdempotencyRecord(other.order_id, False)


async def test_retry_after_unavailable_succeeds(call: Checkout, stock: FakeStock) -> None:
    stock.error = DependencyUnavailable("catalog")
    with pytest.raises(DependencyUnavailable):
        await call()
    stock.error = None

    response = await call()

    assert response.order.status == orders_pb2.ORDER_STATUS_CREATED


async def test_failure_after_reserve_releases_stock(
    call: Checkout,
    catalog: FakeCatalog,
    idempotency: FakeIdempotency,
    repository: FakeRepository,
    stock: FakeStock,
) -> None:
    del catalog.products["p-2"]

    with pytest.raises(FailedPrecondition) as info:
        await call()

    [(order_id, _)] = stock.reserve_calls
    assert [(v.type, v.subject) for v in info.value.violations] == [
        ("PRODUCT_NOT_FOUND", "product:p-2")
    ]
    assert stock.quietly_released == [order_id]
    assert repository.orders == {}
    assert idempotency.records == {}


class HangingCatalog(FakeCatalog):
    """Catalog, который не отвечает, пока вызов не отменят."""

    def __init__(self, catalog: FakeCatalog) -> None:
        super().__init__(catalog.products.values())
        self.called = asyncio.Event()

    async def get_product(self, product_id: str) -> None:
        self.called.set()
        await asyncio.Event().wait()


async def test_cancel_after_reserve_releases_stock(
    carts: FakeCarts,
    catalog: FakeCatalog,
    idempotency: FakeIdempotency,
    repository: FakeRepository,
    stock: FakeStock,
    settings: OrderSettings,
) -> None:
    carts.carts[BUYER_ID] = {"p-1": 1}
    hanging = HangingCatalog(catalog)
    call = Checkout(carts, idempotency, repository, stock, hanging, settings)

    task = asyncio.create_task(call())
    await hanging.called.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    [(order_id, _)] = stock.reserve_calls
    assert stock.quietly_released == [order_id]
    assert repository.orders == {}


async def test_key_in_progress_is_failed_precondition(
    call: Checkout, idempotency: FakeIdempotency, stock: FakeStock
) -> None:
    idempotency.records[BUYER_ID, "key-1"] = IdempotencyRecord("o-pending", pending=True)

    with pytest.raises(FailedPrecondition) as info:
        await call()

    assert [v.type for v in info.value.violations] == ["CHECKOUT_IN_PROGRESS"]
    assert stock.reserve_calls == []


async def test_key_of_vanished_order_is_reused(
    call: Checkout, idempotency: FakeIdempotency
) -> None:
    idempotency.records[BUYER_ID, "key-1"] = IdempotencyRecord("o-gone", pending=False)

    response = await call()

    assert response.order.order_id != "o-gone"
    assert idempotency.records[BUYER_ID, "key-1"].order_id == response.order.order_id


class RacingIdempotency(FakeIdempotency):
    """Параллельный Checkout с тем же ключом успевает между get() и claim()."""

    def __init__(self, winner_order_id: str) -> None:
        super().__init__()
        self.winner_order_id = winner_order_id

    async def claim(self, user_id: str, key: str, order_id: str) -> bool:
        self.records[user_id, key] = IdempotencyRecord(self.winner_order_id, pending=False)
        return False


async def test_lost_claim_race_returns_winner_order(
    carts: FakeCarts,
    repository: FakeRepository,
    stock: FakeStock,
    catalog: FakeCatalog,
    settings: OrderSettings,
) -> None:
    carts.carts[BUYER_ID] = {"p-1": 1}
    winner = repository.add()
    call = Checkout(carts, RacingIdempotency(winner.order_id), repository, stock, catalog, settings)

    response = await call()

    assert response.order.order_id == winner.order_id
    assert stock.reserve_calls == []


async def test_lost_claim_race_without_winner_order_is_busy(
    carts: FakeCarts,
    repository: FakeRepository,
    stock: FakeStock,
    catalog: FakeCatalog,
    settings: OrderSettings,
) -> None:
    carts.carts[BUYER_ID] = {"p-1": 1}
    # Ключ занят заказом, которого уже нет в базе: повторять надо позже, резерва нет
    call = Checkout(carts, RacingIdempotency("vanished"), repository, stock, catalog, settings)

    with pytest.raises(FailedPrecondition) as info:
        await call()

    assert info.value.message == "Idempotency key is busy, retry"
    assert stock.reserve_calls == []


class SlowCommitIdempotency(FakeIdempotency):
    """commit() ждёт сигнала: вызов успевают отменить после создания заказа."""

    def __init__(self) -> None:
        super().__init__()
        self.committing = asyncio.Event()
        self.proceed = asyncio.Event()

    async def commit(self, user_id: str, key: str, order_id: str, ttl_seconds: int) -> bool:
        self.committing.set()
        await self.proceed.wait()
        return await super().commit(user_id, key, order_id, ttl_seconds)


async def test_cancel_after_order_created_still_commits_key(
    carts: FakeCarts,
    repository: FakeRepository,
    stock: FakeStock,
    catalog: FakeCatalog,
    settings: OrderSettings,
) -> None:
    carts.carts[BUYER_ID] = {"p-1": 1}
    idempotency = SlowCommitIdempotency()
    call = Checkout(carts, idempotency, repository, stock, catalog, settings)

    task = asyncio.create_task(call())
    await idempotency.committing.wait()
    task.cancel()
    idempotency.proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)

    [order_id] = repository.orders
    assert idempotency.records[BUYER_ID, "key-1"] == IdempotencyRecord(order_id, pending=False)
    assert BUYER_ID not in carts.carts
    assert stock.quietly_released == []
