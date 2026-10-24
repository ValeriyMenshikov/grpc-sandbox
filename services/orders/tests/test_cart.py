from unittest.mock import Mock

import pytest
from order_service.handlers.add_cart_item_u_u import add_cart_item
from order_service.handlers.get_cart_u_u import get_cart
from order_service.handlers.remove_cart_item_u_u import remove_cart_item
from orders.v1 import orders_pb2
from stand_core.grpc import CurrentUser, InvalidArgument, NotFound

from .fakes import BUYER_ID, FakeCarts, FakeCatalog

pytestmark = pytest.mark.usefixtures("buyer")


async def test_add_accumulates_quantity_and_returns_priced_cart(
    context: Mock, carts: FakeCarts, catalog: FakeCatalog
) -> None:
    await add_cart_item(
        orders_pb2.AddCartItemRequest(product_id="p-1", quantity=1), context, carts, catalog
    )
    response = await add_cart_item(
        orders_pb2.AddCartItemRequest(product_id="p-1", quantity=2), context, carts, catalog
    )

    [item] = response.cart.items
    assert (item.product_id, item.name, item.quantity, item.available) == ("p-1", "Наушники", 3, 10)
    assert (item.unit_price.units, item.unit_price.nanos) == (1999, 900_000_000)
    assert (response.cart.total.currency_code, response.cart.total.units) == ("RUB", 5999)
    assert response.cart.total.nanos == 700_000_000
    assert carts.carts[BUYER_ID] == {"p-1": 3}


async def test_add_unknown_product_is_not_found(
    context: Mock, carts: FakeCarts, catalog: FakeCatalog
) -> None:
    with pytest.raises(NotFound):
        await add_cart_item(
            orders_pb2.AddCartItemRequest(product_id="missing", quantity=1),
            context,
            carts,
            catalog,
        )
    assert carts.carts == {}


async def test_add_validates_product_and_quantity(
    context: Mock, carts: FakeCarts, catalog: FakeCatalog
) -> None:
    with pytest.raises(InvalidArgument) as info:
        await add_cart_item(orders_pb2.AddCartItemRequest(quantity=0), context, carts, catalog)

    assert [v.field for v in info.value.field_violations] == ["product_id", "quantity"]


async def test_remove_item(context: Mock, carts: FakeCarts, catalog: FakeCatalog) -> None:
    carts.carts[BUYER_ID] = {"p-1": 1, "p-2": 2}

    response = await remove_cart_item(
        orders_pb2.RemoveCartItemRequest(product_id="p-1"), context, carts, catalog
    )

    assert [item.product_id for item in response.cart.items] == ["p-2"]
    assert response.cart.total.units == 1000


async def test_remove_absent_item_is_not_found(
    context: Mock, carts: FakeCarts, catalog: FakeCatalog
) -> None:
    with pytest.raises(NotFound):
        await remove_cart_item(
            orders_pb2.RemoveCartItemRequest(product_id="p-1"), context, carts, catalog
        )
    with pytest.raises(InvalidArgument):
        await remove_cart_item(orders_pb2.RemoveCartItemRequest(), context, carts, catalog)


async def test_get_cart_uses_current_prices_and_skips_vanished_products(
    context: Mock, carts: FakeCarts, catalog: FakeCatalog
) -> None:
    carts.carts[BUYER_ID] = {"p-2": 2, "gone": 1}
    catalog.products["p-2"].price_kopecks = 450_00
    catalog.products["p-2"].stock = 1

    response = await get_cart(orders_pb2.GetCartRequest(), context, carts, catalog)

    [item] = response.cart.items
    assert (item.product_id, item.unit_price.units, item.available) == ("p-2", 450, 1)
    assert response.cart.total.units == 900


async def test_empty_cart_has_zero_total(
    context: Mock, carts: FakeCarts, catalog: FakeCatalog
) -> None:
    response = await get_cart(orders_pb2.GetCartRequest(), context, carts, catalog)

    assert list(response.cart.items) == []
    assert (response.cart.total.currency_code, response.cart.total.units) == ("RUB", 0)


async def test_carts_are_per_user(
    context: Mock, carts: FakeCarts, catalog: FakeCatalog, buyer: CurrentUser
) -> None:
    carts.carts["someone-else"] = {"p-1": 5}

    response = await get_cart(orders_pb2.GetCartRequest(), context, carts, catalog)

    assert list(response.cart.items) == []
