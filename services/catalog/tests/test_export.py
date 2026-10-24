from datetime import timedelta
from unittest.mock import Mock

import pytest
from catalog.v1 import catalog_pb2
from catalog_service.handlers.export_products_u_s import export_products
from google.protobuf.timestamp_pb2 import Timestamp

from .fakes import BUYER_ID, FakeRepository


@pytest.fixture
def products(repository: FakeRepository) -> FakeRepository:
    repository.add("OF-1", "Первый")
    repository.add("OF-2", "Второй")
    repository.add("OF-3", "Чужой", seller_id=BUYER_ID)
    repository.add("OF-4", "Третий")
    return repository


@pytest.mark.usefixtures("seller")
async def test_streams_only_current_seller_products(
    products: FakeRepository, context: Mock
) -> None:
    exported = [
        message.product.offer_id
        async for message in export_products(catalog_pb2.ExportProductsRequest(), context, products)
    ]

    assert exported == ["OF-1", "OF-2", "OF-4"]
    assert products.export_closed


@pytest.mark.usefixtures("seller")
async def test_updated_since_filter(products: FakeRepository, context: Mock) -> None:
    second = next(p for p in products.products.values() if p.offer_id == "OF-2")
    since = Timestamp()
    since.FromDatetime(second.updated_at - timedelta(seconds=1))

    exported = [
        message.product.offer_id
        async for message in export_products(
            catalog_pb2.ExportProductsRequest(updated_since=since), context, products
        )
    ]

    assert exported == ["OF-2", "OF-4"]


@pytest.mark.usefixtures("seller")
async def test_stops_when_call_is_done(products: FakeRepository, context: Mock) -> None:
    context.done.side_effect = [False, True]

    exported = [
        message.product.offer_id
        async for message in export_products(catalog_pb2.ExportProductsRequest(), context, products)
    ]

    assert exported == ["OF-1"]
    assert products.export_closed
