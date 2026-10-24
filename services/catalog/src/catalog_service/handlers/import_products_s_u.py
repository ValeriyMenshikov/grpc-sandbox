from collections.abc import AsyncIterator

from catalog.v1 import catalog_pb2
from stand_core import Context, rpc
from stand_core.grpc import (
    FieldViolation,
    InvalidArgument,
    QuotaViolation,
    ResourceExhausted,
    current_user,
)

from catalog_service.models import ImportItem, ImportMode, ImportOutcome
from catalog_service.repository import CatalogRepository
from catalog_service.settings import CatalogSettings

MODES: dict[int, ImportMode] = {
    catalog_pb2.IMPORT_MODE_UPSERT: ImportMode.UPSERT,
    catalog_pb2.IMPORT_MODE_CREATE_ONLY: ImportMode.CREATE_ONLY,
}
MAX_OFFER_ID_LENGTH = 64
MAX_NAME_LENGTH = 255
MAX_CATEGORY_LENGTH = 64


def parse_header(message: catalog_pb2.ImportProductsRequest) -> ImportMode:
    if message.WhichOneof("payload") != "header":
        raise InvalidArgument(
            [FieldViolation("header", "the first message must be the import header")]
        )
    mode = MODES.get(message.header.mode)
    if mode is None:
        raise InvalidArgument(
            [FieldViolation("header.mode", "must be IMPORT_MODE_UPSERT or IMPORT_MODE_CREATE_ONLY")]
        )
    return mode


def validate_row(row: catalog_pb2.ImportRow) -> tuple[ImportItem, list[FieldViolation]]:
    """Строка фида без пробелов по краям и ошибки её полей (пусто — строка годится)."""
    item = ImportItem(
        offer_id=row.offer_id.strip(),
        name=row.name.strip(),
        category=row.category.strip(),
        price_kopecks=row.price_kopecks,
        stock=row.stock,
    )
    violations = [
        FieldViolation(field, "must not be empty")
        for field, value in (
            ("offer_id", item.offer_id),
            ("name", item.name),
            ("category", item.category),
        )
        if not value
    ]
    violations += [
        FieldViolation(field, f"must be at most {limit} characters")
        for field, value, limit in (
            ("offer_id", item.offer_id, MAX_OFFER_ID_LENGTH),
            ("name", item.name, MAX_NAME_LENGTH),
            ("category", item.category, MAX_CATEGORY_LENGTH),
        )
        if len(value) > limit
    ]
    if item.price_kopecks <= 0:
        violations.append(FieldViolation("price_kopecks", "must be positive"))
    if item.stock < 0:
        violations.append(FieldViolation("stock", "must not be negative"))
    return item, violations


def row_error(row_number: int, violation: FieldViolation) -> catalog_pb2.ImportRowError:
    return catalog_pb2.ImportRowError(
        row_number=row_number, field=violation.field, description=violation.description
    )


@rpc("ImportProducts", package="catalog.v1", service="CatalogService")
async def import_products(
    request: AsyncIterator[catalog_pb2.ImportProductsRequest],
    context: Context,
    repository: CatalogRepository,
    settings: CatalogSettings,
) -> catalog_pb2.ImportProductsResponse:
    """Сначала читаем и проверяем весь фид, потом пишем его одной транзакцией.

    Так стрим сверх IMPORT_MAX_ROWS отклоняется целиком, без частично применённого импорта.
    """
    seller = current_user()
    mode: ImportMode | None = None
    valid: list[tuple[int, ImportItem]] = []
    errors: list[catalog_pb2.ImportRowError] = []
    row_number = 0

    async for message in request:
        if mode is None:
            mode = parse_header(message)
            continue
        if message.WhichOneof("payload") == "header":
            raise InvalidArgument([FieldViolation("header", "the import header must be sent once")])
        row_number += 1
        if row_number > settings.import_max_rows:
            raise ResourceExhausted(
                [
                    QuotaViolation(
                        subject=f"seller:{seller.id}",
                        description=f"ImportProducts accepts at most "
                        f"{settings.import_max_rows} rows per stream",
                    )
                ],
                message=f"Too many rows: the limit is {settings.import_max_rows}",
            )
        item, violations = validate_row(message.row)
        if violations:
            errors += [row_error(row_number, violation) for violation in violations]
        else:
            valid.append((row_number, item))

    if mode is None:
        raise InvalidArgument([FieldViolation("header", "the import header is missing")])

    outcomes = (
        await repository.import_products(seller.id, mode, [item for _, item in valid])
        if valid
        else []
    )
    created = updated = 0
    for (number, _), outcome in zip(valid, outcomes, strict=True):
        if outcome is ImportOutcome.CREATED:
            created += 1
        elif outcome is ImportOutcome.UPDATED:
            updated += 1
        else:
            errors.append(
                row_error(number, FieldViolation("offer_id", "product with this offer_id exists"))
            )
    errors.sort(key=lambda error: error.row_number)
    return catalog_pb2.ImportProductsResponse(
        created=created,
        updated=updated,
        failed=len({error.row_number for error in errors}),
        errors=errors,
    )
