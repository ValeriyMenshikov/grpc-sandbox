from unittest.mock import Mock

import pytest
from catalog.v1 import catalog_pb2 as v1
from catalog.v2 import catalog_pb2 as v2
from catalog_service.handlers.get_product_u_u import get_product
from catalog_service.handlers.v2_get_product_u_u import get_product_v2
from stand_core.grpc import FieldViolation, InvalidArgument, NotFound

from .fakes import FakeRepository


async def test_v1_returns_product_with_kopecks(repository: FakeRepository, context: Mock) -> None:
    product = repository.add("EL-1", "Наушники", price_kopecks=899_050, stock=7)

    response = await get_product(
        v1.GetProductRequest(product_id=product.product_id), context, repository
    )

    assert response.product.product_id == product.product_id
    assert response.product.offer_id == "EL-1"
    assert response.product.price_kopecks == 899_050
    assert response.product.stock == 7
    assert response.product.updated_at.ToDatetime().year == 2026


async def test_v2_returns_same_product_with_money(
    repository: FakeRepository, context: Mock
) -> None:
    product = repository.add("EL-1", "Наушники", price_kopecks=899_050)

    response = await get_product_v2(
        v2.GetProductRequest(product_id=product.product_id), context, repository
    )

    assert response.product.name == "Наушники"
    assert response.product.price.currency_code == "RUB"
    assert (response.product.price.units, response.product.price.nanos) == (8990, 500_000_000)


async def test_unknown_product_is_not_found_in_both_versions(
    repository: FakeRepository, context: Mock
) -> None:
    with pytest.raises(NotFound) as v1_info:
        await get_product(v1.GetProductRequest(product_id="missing"), context, repository)
    with pytest.raises(NotFound) as v2_info:
        await get_product_v2(v2.GetProductRequest(product_id="missing"), context, repository)

    for info in (v1_info, v2_info):
        assert (info.value.resource_type, info.value.resource_name) == ("product", "missing")


async def test_empty_product_id_is_invalid(repository: FakeRepository, context: Mock) -> None:
    with pytest.raises(InvalidArgument) as info:
        await get_product(v1.GetProductRequest(), context, repository)
    assert info.value.field_violations == [FieldViolation("product_id", "must not be empty")]
