from collections.abc import AsyncIterator
from unittest.mock import Mock

import pytest
from catalog.v1 import catalog_pb2
from catalog_service.handlers.import_products_s_u import MAX_PRICE_KOPECKS, import_products
from catalog_service.models import ImportMode
from catalog_service.settings import CatalogSettings
from stand_core.grpc import CurrentUser, InvalidArgument, ResourceExhausted

from .fakes import SELLER_ID, FakeRepository


def header(
    mode: catalog_pb2.ImportMode.ValueType = catalog_pb2.IMPORT_MODE_UPSERT,
) -> catalog_pb2.ImportProductsRequest:
    return catalog_pb2.ImportProductsRequest(header=catalog_pb2.ImportHeader(mode=mode))


def row(
    offer_id: str,
    name: str = "Товар",
    *,
    category: str = "books",
    price_kopecks: int = 1000,
    stock: int = 3,
) -> catalog_pb2.ImportProductsRequest:
    return catalog_pb2.ImportProductsRequest(
        row=catalog_pb2.ImportRow(
            offer_id=offer_id,
            name=name,
            category=category,
            price_kopecks=price_kopecks,
            stock=stock,
        )
    )


async def stream(
    *messages: catalog_pb2.ImportProductsRequest,
) -> AsyncIterator[catalog_pb2.ImportProductsRequest]:
    for message in messages:
        yield message


async def run(
    repository: FakeRepository,
    settings: CatalogSettings,
    *messages: catalog_pb2.ImportProductsRequest,
) -> catalog_pb2.ImportProductsResponse:
    return await import_products(stream(*messages), Mock(), repository, settings)


@pytest.mark.usefixtures("seller")
async def test_upsert_creates_and_updates(
    repository: FakeRepository, settings: CatalogSettings
) -> None:
    existing = repository.add("OF-1", "Старое название")

    report = await run(repository, settings, header(), row(" OF-1 ", "Новое название"), row("OF-2"))

    assert (report.created, report.updated, report.failed) == (1, 1, 0)
    assert list(report.errors) == []
    assert repository.products[existing.product_id].name == "Новое название"
    seller_id, mode, items = repository.imports[0]
    assert (seller_id, mode) == (SELLER_ID, ImportMode.UPSERT)
    assert [item.offer_id for item in items] == ["OF-1", "OF-2"]


@pytest.mark.usefixtures("seller")
async def test_bad_rows_are_reported_without_failing_import(
    repository: FakeRepository, settings: CatalogSettings
) -> None:
    report = await run(
        repository,
        settings,
        header(),
        row("OF-1"),
        row("", "", price_kopecks=0),
        row("OF-3", stock=-1),
        row("OF-4", category="x" * 65),
        row("OF-5", price_kopecks=MAX_PRICE_KOPECKS + 1),
    )

    assert (report.created, report.updated, report.failed) == (1, 0, 4)
    assert [(e.row_number, e.field) for e in report.errors] == [
        (2, "offer_id"),
        (2, "name"),
        (2, "price_kopecks"),
        (3, "stock"),
        (4, "category"),
        (5, "price_kopecks"),
    ]
    assert report.errors[0].description == "must not be empty"


@pytest.mark.usefixtures("seller")
async def test_create_only_reports_existing_offer_id(
    repository: FakeRepository, settings: CatalogSettings
) -> None:
    repository.add("OF-1", "Уже есть")

    report = await run(
        repository,
        settings,
        header(catalog_pb2.IMPORT_MODE_CREATE_ONLY),
        row("OF-1"),
        row("OF-2"),
        row("OF-2"),
    )

    assert (report.created, report.updated, report.failed) == (1, 0, 2)
    assert [(e.row_number, e.field) for e in report.errors] == [(1, "offer_id"), (3, "offer_id")]
    assert repository.imports[0][1] is ImportMode.CREATE_ONLY


@pytest.mark.usefixtures("seller")
@pytest.mark.parametrize(
    ("messages", "field"),
    [
        ((), "header"),
        ((row("OF-1"),), "header"),
        ((catalog_pb2.ImportProductsRequest(),), "header"),
        ((header(catalog_pb2.IMPORT_MODE_UNSPECIFIED), row("OF-1")), "header.mode"),
        ((header(), row("OF-1"), header()), "header"),
    ],
)
async def test_stream_without_valid_header_is_invalid(
    repository: FakeRepository,
    settings: CatalogSettings,
    messages: tuple[catalog_pb2.ImportProductsRequest, ...],
    field: str,
) -> None:
    with pytest.raises(InvalidArgument) as info:
        await run(repository, settings, *messages)

    assert [v.field for v in info.value.field_violations] == [field]
    assert repository.imports == []


async def test_row_limit_is_resource_exhausted(
    repository: FakeRepository, settings: CatalogSettings, seller: CurrentUser
) -> None:
    rows = [row(f"OF-{index}") for index in range(settings.import_max_rows + 1)]

    with pytest.raises(ResourceExhausted) as info:
        await run(repository, settings, header(), *rows)

    assert settings.import_max_rows == 5
    [violation] = info.value.violations
    assert violation.subject == f"seller:{seller.id}"
    assert "at most 5 rows" in violation.description
    # Ни одна строка не записана: лимит проверяется до записи
    assert repository.imports == []


@pytest.mark.usefixtures("seller")
async def test_exactly_limit_rows_is_fine(
    repository: FakeRepository, settings: CatalogSettings
) -> None:
    rows = [row(f"OF-{index}") for index in range(settings.import_max_rows)]

    report = await run(repository, settings, header(), *rows)

    assert report.created == settings.import_max_rows


@pytest.mark.usefixtures("seller")
async def test_header_only_imports_nothing(
    repository: FakeRepository, settings: CatalogSettings
) -> None:
    report = await run(repository, settings, header())

    assert (report.created, report.updated, report.failed) == (0, 0, 0)
    assert repository.imports == []
