from unittest.mock import Mock

import pytest
from catalog.v1 import catalog_pb2 as v1
from catalog.v2 import catalog_pb2 as v2
from catalog_service.handlers.search_products_u_u import search_products
from catalog_service.handlers.v2_search_products_u_u import search_products_v2
from catalog_service.search import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    decode_page_token,
    encode_page_token,
)
from common.v1 import money_pb2
from stand_core.grpc import FieldViolation, InvalidArgument

from .fakes import FakeRepository


@pytest.fixture
def catalog(repository: FakeRepository) -> FakeRepository:
    repository.add("BK-1", "Книга про Python", category="books", price_kopecks=150_000)
    repository.add("BK-2", "Книга про gRPC", category="books", price_kopecks=250_000)
    repository.add("EL-1", "Наушники", category="electronics", price_kopecks=900_000)
    repository.add("EL-2", "Кабель USB-C", category="electronics", price_kopecks=50_000)
    repository.add("HM-1", "Чайник", category="home", price_kopecks=350_000)
    return repository


def names(response: v1.SearchProductsResponse | v2.SearchProductsResponse) -> list[str]:
    return [product.name for product in response.products]


async def test_filters_by_text_category_and_price(catalog: FakeRepository, context: Mock) -> None:
    response = await search_products(
        v1.SearchProductsRequest(
            query="  книга ", category="books", min_price_kopecks=200_000, max_price_kopecks=300_000
        ),
        context,
        catalog,
    )

    assert names(response) == ["Книга про gRPC"]
    assert response.next_page_token == ""


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        (v1.SORT_ORDER_UNSPECIFIED, ["Кабель USB-C", "Книга про Python", "Книга про gRPC"]),
        (v1.SORT_ORDER_PRICE_ASC, ["Кабель USB-C", "Книга про Python", "Книга про gRPC"]),
        (v1.SORT_ORDER_PRICE_DESC, ["Наушники", "Чайник", "Книга про gRPC"]),
        (v1.SORT_ORDER_NEWEST, ["Чайник", "Кабель USB-C", "Наушники"]),
    ],
)
async def test_sort_orders(
    catalog: FakeRepository, context: Mock, sort: v1.SortOrder.ValueType, expected: list[str]
) -> None:
    response = await search_products(
        v1.SearchProductsRequest(sort=sort, pagination=money_pb2.Pagination(page_size=3)),
        context,
        catalog,
    )

    assert names(response) == expected


async def test_pages_follow_next_page_token(catalog: FakeRepository, context: Mock) -> None:
    seen: list[str] = []
    token = ""
    for _ in range(3):
        response = await search_products(
            v1.SearchProductsRequest(
                sort=v1.SORT_ORDER_PRICE_ASC,
                pagination=money_pb2.Pagination(page_size=2, page_token=token),
            ),
            context,
            catalog,
        )
        seen += names(response)
        token = response.next_page_token
        if not token:
            break

    assert len(seen) == 5
    assert len(set(seen)) == 5
    assert token == ""


@pytest.mark.parametrize(
    "token",
    [
        "not-base64!",
        "e30=",  # {} — нет offset
        "eyJvZmZzZXQiOiAtMX0=",  # offset < 0
        "eyJvZmZzZXQiOiA5MjIzMzcyMDM2ODU0Nzc1ODA4fQ==",  # offset = 2**63, не влезает в bigint
        "eyJvZmZzZXQiOiAiMTAifQ==",  # offset — строка
        "eyJvZmZzZXQiOiB0cnVlfQ==",  # offset — bool
    ],
)
async def test_invalid_page_token(catalog: FakeRepository, context: Mock, token: str) -> None:
    with pytest.raises(InvalidArgument) as info:
        await search_products(
            v1.SearchProductsRequest(pagination=money_pb2.Pagination(page_token=token)),
            context,
            catalog,
        )
    assert info.value.field_violations == [
        FieldViolation("pagination.page_token", "invalid page token")
    ]


def test_page_token_round_trip() -> None:
    assert decode_page_token(encode_page_token(40)) == 40
    assert decode_page_token("") == 0


async def test_page_size_default_and_cap(repository: FakeRepository, context: Mock) -> None:
    for index in range(MAX_PAGE_SIZE + 5):
        repository.add(f"OF-{index}", f"Товар {index:03}")

    default = await search_products(v1.SearchProductsRequest(), context, repository)
    capped = await search_products(
        v1.SearchProductsRequest(pagination=money_pb2.Pagination(page_size=1000)),
        context,
        repository,
    )

    assert len(default.products) == DEFAULT_PAGE_SIZE
    assert len(capped.products) == MAX_PAGE_SIZE
    assert capped.next_page_token


async def test_negative_page_size_and_bad_price_range(
    catalog: FakeRepository, context: Mock
) -> None:
    with pytest.raises(InvalidArgument) as size_info:
        await search_products(
            v1.SearchProductsRequest(pagination=money_pb2.Pagination(page_size=-1)),
            context,
            catalog,
        )
    with pytest.raises(InvalidArgument) as price_info:
        await search_products(
            v1.SearchProductsRequest(min_price_kopecks=500, max_price_kopecks=100),
            context,
            catalog,
        )

    assert [v.field for v in size_info.value.field_violations] == ["pagination.page_size"]
    assert [v.field for v in price_info.value.field_violations] == ["min_price_kopecks"]


async def test_v2_requires_region_id(catalog: FakeRepository, context: Mock) -> None:
    with pytest.raises(InvalidArgument) as info:
        await search_products_v2(v2.SearchProductsRequest(region_id="  "), context, catalog)
    assert info.value.field_violations == [FieldViolation("region_id", "is required")]


async def test_v2_filters_by_money_and_returns_money(
    catalog: FakeRepository, context: Mock
) -> None:
    response = await search_products_v2(
        v2.SearchProductsRequest(
            region_id="msk",
            min_price=money_pb2.Money(currency_code="RUB", units=1500),
            max_price=money_pb2.Money(units=2500, nanos=0),
            sort=v2.SORT_ORDER_PRICE_DESC,
        ),
        context,
        catalog,
    )

    assert names(response) == ["Книга про gRPC", "Книга про Python"]
    assert response.products[0].price == money_pb2.Money(currency_code="RUB", units=2500)


async def test_v2_rejects_bad_money(catalog: FakeRepository, context: Mock) -> None:
    with pytest.raises(InvalidArgument) as info:
        await search_products_v2(
            v2.SearchProductsRequest(
                region_id="msk",
                min_price=money_pb2.Money(currency_code="USD", units=1),
                max_price=money_pb2.Money(units=1, nanos=5),
            ),
            context,
            catalog,
        )
    assert [v.field for v in info.value.field_violations] == [
        "min_price.currency_code",
        "max_price.nanos",
    ]
