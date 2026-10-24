"""Поиск товаров, общий для catalog.v1 и catalog.v2: пагинация и проверка фильтров."""

import base64
import binascii
import json
from dataclasses import dataclass

from common.v1 import money_pb2
from stand_core.grpc import FieldViolation, InvalidArgument

from catalog_service.models import Product, ProductFilter
from catalog_service.repository import CatalogRepository

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
# Смещение уходит в Postgres OFFSET (bigint): больше — битый токен, а не ошибка базы
MAX_PAGE_OFFSET = 2**63 - 1
PAGE_TOKEN_FIELD = "pagination.page_token"


@dataclass(frozen=True)
class Page:
    products: list[Product]
    next_page_token: str


def encode_page_token(offset: int) -> str:
    """Непрозрачный для клиента токен: base64url от JSON со смещением."""
    return base64.urlsafe_b64encode(json.dumps({"offset": offset}).encode()).decode()


def decode_page_token(token: str) -> int:
    """Смещение из токена; пустой токен — первая страница, битый — INVALID_ARGUMENT."""
    if not token:
        return 0
    try:
        data = json.loads(base64.urlsafe_b64decode(token.encode("ascii")))
        offset = data["offset"]
    except (ValueError, TypeError, KeyError, binascii.Error):
        offset = None
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or not 0 <= offset <= MAX_PAGE_OFFSET
    ):
        raise InvalidArgument([FieldViolation(PAGE_TOKEN_FIELD, "invalid page token")])
    return offset


def page_size(requested: int) -> int:
    if requested < 0:
        raise InvalidArgument([FieldViolation("pagination.page_size", "must not be negative")])
    return min(requested or DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)


def price_range_violations(
    min_price: int | None, max_price: int | None, min_field: str, max_field: str
) -> list[FieldViolation]:
    violations = [
        FieldViolation(field, "must not be negative")
        for field, price in ((min_field, min_price), (max_field, max_price))
        if price is not None and price < 0
    ]
    if min_price is not None and max_price is not None and min_price > max_price:
        violations.append(FieldViolation(min_field, f"must not be greater than {max_field}"))
    return violations


async def search_page(
    repository: CatalogRepository,
    product_filter: ProductFilter,
    pagination: money_pb2.Pagination,
) -> Page:
    """Страница результатов; на одну запись больше лимита — признак следующей страницы."""
    limit = page_size(pagination.page_size)
    offset = decode_page_token(pagination.page_token)
    products = await repository.search_products(product_filter, offset, limit + 1)
    has_next = len(products) > limit
    return Page(
        products=products[:limit],
        next_page_token=encode_page_token(offset + limit) if has_next else "",
    )
