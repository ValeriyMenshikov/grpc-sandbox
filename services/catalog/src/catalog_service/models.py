"""Доменные типы каталога: репозиторий и хэндлеры не зависят от версий proto."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True)
class Product:
    product_id: str
    seller_id: str
    offer_id: str
    name: str
    category: str
    price_kopecks: int
    # Доступный остаток: остаток на складе минус резервы
    stock: int
    created_at: datetime
    updated_at: datetime


class ProductSort(StrEnum):
    NAME = "name"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    NEWEST = "newest"


@dataclass(frozen=True)
class ProductFilter:
    # Подстрока в названии без учёта регистра; пусто — все товары
    query: str = ""
    category: str | None = None
    min_price_kopecks: int | None = None
    max_price_kopecks: int | None = None
    sort: ProductSort = ProductSort.NAME


class ImportMode(StrEnum):
    UPSERT = "upsert"
    CREATE_ONLY = "create_only"


class ImportOutcome(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    # CREATE_ONLY и offer_id уже есть у продавца
    ALREADY_EXISTS = "already_exists"


@dataclass(frozen=True)
class ImportItem:
    offer_id: str
    name: str
    category: str
    price_kopecks: int
    stock: int


@dataclass(frozen=True)
class StockItem:
    product_id: str
    quantity: int


@dataclass(frozen=True)
class StockShortage:
    product_id: str
    requested: int
    # Доступный остаток; None — товара нет в каталоге
    available: int | None


@dataclass(frozen=True)
class ReserveResult:
    """Итог ReserveStock: либо зарезервированы все позиции, либо (при нехватке) ни одной."""

    items: list[StockItem]
    shortages: list[StockShortage]
