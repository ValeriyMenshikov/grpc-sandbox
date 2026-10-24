"""Репозиторий каталога в памяти для unit-тестов хэндлеров (без Postgres)."""

from collections.abc import AsyncGenerator, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from catalog_service.models import (
    ImportItem,
    ImportMode,
    ImportOutcome,
    Product,
    ProductFilter,
    ProductSort,
    ReserveResult,
    StockItem,
    StockShortage,
)
from catalog_service.repository import CatalogRepository

SELLER_ID = "seller-1"
BUYER_ID = "buyer-1"
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


class FakeRepository(CatalogRepository):
    def __init__(self) -> None:
        self.products: dict[str, Product] = {}
        self.imports: list[tuple[str, ImportMode, list[ImportItem]]] = []
        self.export_closed = False
        # order_id → зарезервированные позиции; Product.stock здесь — остаток без учёта резервов
        self.reservations: dict[str, list[StockItem]] = {}
        self._clock = EPOCH

    async def connect(self) -> None:
        pass

    def tick(self) -> datetime:
        self._clock += timedelta(minutes=1)
        return self._clock

    def add(
        self,
        offer_id: str,
        name: str,
        *,
        category: str = "books",
        price_kopecks: int = 10_000,
        stock: int = 5,
        seller_id: str = SELLER_ID,
    ) -> Product:
        now = self.tick()
        product = Product(
            product_id=f"p-{len(self.products) + 1}",
            seller_id=seller_id,
            offer_id=offer_id,
            name=name,
            category=category,
            price_kopecks=price_kopecks,
            stock=stock,
            created_at=now,
            updated_at=now,
        )
        self.products[product.product_id] = product
        return product

    async def get_product(self, product_id: str) -> Product | None:
        return self.products.get(product_id)

    async def search_products(
        self, product_filter: ProductFilter, offset: int, limit: int
    ) -> list[Product]:
        found = [
            product
            for product in self.products.values()
            if product_filter.query.lower() in product.name.lower()
            and product_filter.category in (None, product.category)
            and (
                product_filter.min_price_kopecks is None
                or product.price_kopecks >= product_filter.min_price_kopecks
            )
            and (
                product_filter.max_price_kopecks is None
                or product.price_kopecks <= product_filter.max_price_kopecks
            )
        ]
        match product_filter.sort:
            case ProductSort.NAME:
                found.sort(key=lambda p: (p.name, p.product_id))
            case ProductSort.PRICE_ASC:
                found.sort(key=lambda p: (p.price_kopecks, p.product_id))
            case ProductSort.PRICE_DESC:
                found.sort(key=lambda p: (-p.price_kopecks, p.product_id))
            case ProductSort.NEWEST:
                found.sort(key=lambda p: p.product_id)
                found.sort(key=lambda p: p.updated_at, reverse=True)
        return found[offset : offset + limit]

    async def import_products(
        self, seller_id: str, mode: ImportMode, items: Sequence[ImportItem]
    ) -> list[ImportOutcome]:
        self.imports.append((seller_id, mode, list(items)))
        outcomes = []
        for item in items:
            existing = next(
                (
                    p
                    for p in self.products.values()
                    if (p.seller_id, p.offer_id) == (seller_id, item.offer_id)
                ),
                None,
            )
            if existing is None:
                product = self.add(
                    item.offer_id,
                    item.name,
                    category=item.category,
                    price_kopecks=item.price_kopecks,
                    stock=item.stock,
                    seller_id=seller_id,
                )
                outcomes.append(ImportOutcome.CREATED)
            elif mode is ImportMode.CREATE_ONLY:
                outcomes.append(ImportOutcome.ALREADY_EXISTS)
            else:
                product = replace(
                    existing,
                    name=item.name,
                    category=item.category,
                    price_kopecks=item.price_kopecks,
                    stock=item.stock,
                    updated_at=self.tick(),
                )
                self.products[product.product_id] = product
                outcomes.append(ImportOutcome.UPDATED)
        return outcomes

    async def export_products(
        self, seller_id: str, updated_since: datetime | None
    ) -> AsyncGenerator[Product, None]:
        try:
            for product in sorted(self.products.values(), key=lambda p: p.updated_at):
                if product.seller_id == seller_id and (
                    updated_since is None or product.updated_at >= updated_since
                ):
                    yield product
        finally:
            self.export_closed = True

    async def get_available(self, product_id: str) -> int | None:
        product = self.products.get(product_id)
        if product is None:
            return None
        reserved = sum(
            item.quantity
            for items in self.reservations.values()
            for item in items
            if item.product_id == product_id
        )
        return max(product.stock - reserved, 0)

    async def reserve_stock(self, order_id: str, items: Sequence[StockItem]) -> ReserveResult:
        if order_id in self.reservations:
            return ReserveResult(items=self.reservations[order_id], shortages=[])
        shortages = []
        for item in items:
            available = await self.get_available(item.product_id)
            if available is None or available < item.quantity:
                shortages.append(StockShortage(item.product_id, item.quantity, available))
        if shortages:
            return ReserveResult(items=[], shortages=shortages)
        self.reservations[order_id] = list(items)
        return ReserveResult(items=list(items), shortages=[])

    async def release_stock(self, order_id: str) -> bool:
        return self.reservations.pop(order_id, None) is not None
