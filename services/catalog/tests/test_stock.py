import asyncio
import time
from unittest.mock import AsyncMock, Mock

import grpc
import pytest
from catalog.v1 import catalog_pb2 as v1
from catalog_service.handlers.get_stock_u_u import get_stock
from catalog_service.handlers.release_stock_u_u import release_stock
from catalog_service.handlers.reserve_stock_u_u import (
    reserve_delay_ms,
    reserve_stock,
    sleep_within_deadline,
)
from catalog_service.settings import CatalogSettings
from stand_core.grpc import (
    FailedPrecondition,
    FieldViolation,
    InvalidArgument,
    NotFound,
    PreconditionViolation,
)

from .fakes import FakeRepository


def reserve(order_id: str, *items: tuple[str, int]) -> v1.ReserveStockRequest:
    return v1.ReserveStockRequest(
        order_id=order_id,
        items=[v1.StockItem(product_id=pid, quantity=quantity) for pid, quantity in items],
    )


@pytest.fixture
def context() -> Mock:
    """Контекст без metadata и без deadline; abort ведёт себя как в grpc.aio — бросает."""
    context = Mock()
    context.invocation_metadata.return_value = ()
    context.time_remaining.return_value = None
    context.abort = AsyncMock(side_effect=grpc.aio.AbortError())
    return context


async def test_get_stock_subtracts_reservations(
    repository: FakeRepository, context: Mock, settings: CatalogSettings
) -> None:
    product = repository.add("A", "Альфа", stock=5)
    await reserve_stock(reserve("o1", (product.product_id, 2)), context, repository, settings)

    response = await get_stock(
        v1.GetStockRequest(product_id=product.product_id), context, repository
    )

    assert (response.product_id, response.available) == (product.product_id, 3)


async def test_get_stock_unknown_and_empty(repository: FakeRepository, context: Mock) -> None:
    with pytest.raises(NotFound):
        await get_stock(v1.GetStockRequest(product_id="missing"), context, repository)
    with pytest.raises(InvalidArgument):
        await get_stock(v1.GetStockRequest(), context, repository)


async def test_reserve_all_items(
    repository: FakeRepository, context: Mock, settings: CatalogSettings
) -> None:
    a = repository.add("A", "Альфа", stock=5)
    b = repository.add("B", "Бета", stock=1)

    response = await reserve_stock(
        reserve("o1", (a.product_id, 5), (b.product_id, 1)), context, repository, settings
    )

    assert response.order_id == "o1"
    assert [(i.product_id, i.quantity) for i in response.items] == [
        (a.product_id, 5),
        (b.product_id, 1),
    ]
    assert await repository.get_available(a.product_id) == 0


async def test_shortage_reserves_nothing_and_lists_products(
    repository: FakeRepository, context: Mock, settings: CatalogSettings
) -> None:
    a = repository.add("A", "Альфа", stock=5)
    b = repository.add("B", "Бета", stock=1)

    with pytest.raises(FailedPrecondition) as info:
        await reserve_stock(
            reserve("o1", (a.product_id, 2), (b.product_id, 3), ("missing", 1)),
            context,
            repository,
            settings,
        )

    assert info.value.violations == [
        PreconditionViolation(
            "INSUFFICIENT_STOCK", f"product:{b.product_id}", "requested 3, available 1"
        ),
        PreconditionViolation("PRODUCT_NOT_FOUND", "product:missing", "product does not exist"),
    ]
    assert repository.reservations == {}
    assert await repository.get_available(a.product_id) == 5


async def test_repeat_with_same_order_id_is_idempotent(
    repository: FakeRepository, context: Mock, settings: CatalogSettings
) -> None:
    a = repository.add("A", "Альфа", stock=3)
    request = reserve("o1", (a.product_id, 2))

    first = await reserve_stock(request, context, repository, settings)
    # Остатка на второй резерв уже нет, но это повтор того же заказа
    second = await reserve_stock(request, context, repository, settings)

    assert first == second
    assert await repository.get_available(a.product_id) == 1


@pytest.mark.parametrize(
    ("request_", "fields"),
    [
        (reserve("", ("p", 1)), ["order_id"]),
        (reserve("o1"), ["items"]),
        (
            reserve("o1", ("", 1), ("p", 0), ("p", 1)),
            ["items[0].product_id", "items[1].quantity", "items[2].product_id"],
        ),
    ],
)
async def test_reserve_validation(
    repository: FakeRepository,
    context: Mock,
    settings: CatalogSettings,
    request_: v1.ReserveStockRequest,
    fields: list[str],
) -> None:
    with pytest.raises(InvalidArgument) as info:
        await reserve_stock(request_, context, repository, settings)
    assert [v.field for v in info.value.field_violations] == fields


async def test_release_twice(
    repository: FakeRepository, context: Mock, settings: CatalogSettings
) -> None:
    a = repository.add("A", "Альфа", stock=3)
    await reserve_stock(reserve("o1", (a.product_id, 3)), context, repository, settings)

    first = await release_stock(v1.ReleaseStockRequest(order_id="o1"), context, repository)
    second = await release_stock(v1.ReleaseStockRequest(order_id="o1"), context, repository)

    assert (first.order_id, first.released) == ("o1", True)
    assert (second.order_id, second.released) == ("o1", False)
    assert await repository.get_available(a.product_id) == 3


async def test_release_without_order_id_is_invalid(
    repository: FakeRepository, context: Mock
) -> None:
    with pytest.raises(InvalidArgument) as info:
        await release_stock(v1.ReleaseStockRequest(), context, repository)
    assert info.value.field_violations == [FieldViolation("order_id", "must not be empty")]


async def test_delay_from_env(context: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCK_RESERVE_DELAY_MS", "250")
    assert reserve_delay_ms(context, CatalogSettings()) == 250


async def test_delay_from_metadata_overrides_env(
    context: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_RESERVE_DELAY_MS", "250")
    context.invocation_metadata.return_value = (("x-debug-delay-ms", "0"),)
    assert reserve_delay_ms(context, CatalogSettings()) == 0


@pytest.mark.parametrize("value", ["soon", "-1", "1.5"])
async def test_invalid_delay_metadata(context: Mock, settings: CatalogSettings, value: str) -> None:
    context.invocation_metadata.return_value = (("x-debug-delay-ms", value),)
    with pytest.raises(InvalidArgument) as info:
        reserve_delay_ms(context, settings)
    assert info.value.field_violations[0].field == "x-debug-delay-ms"


async def test_delay_is_applied_before_reserve(
    repository: FakeRepository, context: Mock, settings: CatalogSettings
) -> None:
    a = repository.add("A", "Альфа", stock=3)
    context.invocation_metadata.return_value = (("x-debug-delay-ms", "100"),)

    started = time.monotonic()
    await reserve_stock(reserve("o1", (a.product_id, 1)), context, repository, settings)

    assert time.monotonic() - started >= 0.1
    assert "o1" in repository.reservations


async def test_delay_past_deadline_aborts_without_reserve(
    repository: FakeRepository, context: Mock, settings: CatalogSettings
) -> None:
    a = repository.add("A", "Альфа", stock=3)
    context.invocation_metadata.return_value = (("x-debug-delay-ms", "5000"),)
    context.time_remaining.return_value = 0.05

    started = time.monotonic()
    with pytest.raises(grpc.aio.AbortError):
        await reserve_stock(reserve("o1", (a.product_id, 1)), context, repository, settings)

    assert time.monotonic() - started < 1
    context.abort.assert_awaited_once()
    assert context.abort.await_args.args[0] is grpc.StatusCode.DEADLINE_EXCEEDED
    assert repository.reservations == {}


async def test_delay_within_deadline_sleeps_fully(context: Mock) -> None:
    context.time_remaining.return_value = 10.0
    started = asyncio.get_running_loop().time()
    await sleep_within_deadline(context, 50)
    assert asyncio.get_running_loop().time() - started >= 0.05
    context.abort.assert_not_called()
