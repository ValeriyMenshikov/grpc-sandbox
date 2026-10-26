"""Репозиторий, Redis-хранилища и клиенты к catalog в памяти для unit-тестов."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from catalog.v1 import catalog_pb2
from order_service.carts import MAX_CART_QUANTITY, Carts
from order_service.catalog_client import CatalogClient
from order_service.events import OrderEvents, Subscription
from order_service.idempotency import IdempotencyKeys, IdempotencyRecord
from order_service.models import (
    CANCELLABLE_STATUSES,
    NEXT_STATUS,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusEvent,
    StatusChange,
)
from order_service.repository import OrderRepository
from order_service.stock_client import StockClient
from stand_core.grpc import FailedPrecondition, PreconditionViolation

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
BUYER_ID = "u-buyer"
OTHER_ID = "u-other"


class FakeRepository(OrderRepository):
    def __init__(self) -> None:
        self.orders: dict[str, Order] = {}
        self._clock = EPOCH

    async def connect(self) -> None:
        pass

    def tick(self) -> datetime:
        self._clock += timedelta(minutes=1)
        return self._clock

    def add(
        self,
        user_id: str = BUYER_ID,
        status: OrderStatus = OrderStatus.CREATED,
        items: Sequence[OrderItem] = (OrderItem("p-1", "Наушники", 1, 100_00),),
    ) -> Order:
        now = self.tick()
        order = Order(f"o-{len(self.orders) + 1}", user_id, status, tuple(items), now, now)
        self.orders[order.order_id] = order
        return order

    async def create_order(self, order_id: str, user_id: str, items: Sequence[OrderItem]) -> Order:
        now = self.tick()
        order = Order(order_id, user_id, OrderStatus.CREATED, tuple(items), now, now)
        self.orders[order_id] = order
        return order

    async def get_order(self, order_id: str) -> Order | None:
        return self.orders.get(order_id)

    async def list_orders(
        self, user_id: str, status: OrderStatus | None, offset: int, limit: int
    ) -> list[Order]:
        orders = [
            order
            for order in self.orders.values()
            if order.user_id == user_id and (status is None or order.status is status)
        ]
        orders.sort(key=lambda order: (order.created_at, order.order_id), reverse=True)
        return orders[offset : offset + limit]

    async def cancel(self, order_id: str) -> Order | None:
        order = self.orders.get(order_id)
        if order is None or order.status not in CANCELLABLE_STATUSES:
            return None
        order = replace(order, status=OrderStatus.CANCELLED, updated_at=self.tick())
        self.orders[order_id] = order
        return order

    async def advance_due(self, step: timedelta) -> list[OrderStatusEvent]:
        """Каждый заказ в доставке — на шаг вперёд, без учёта `step` (его проверяет SQL-тест)."""
        events = []
        for order in list(self.orders.values()):
            following = NEXT_STATUS.get(order.status)
            if following is None:
                continue
            order = replace(order, status=following, updated_at=self.tick())
            self.orders[order.order_id] = order
            events.append(
                OrderStatusEvent(order.order_id, order.user_id, "", order.status, order.updated_at)
            )
        return events


class FakeCarts(Carts):
    def __init__(self) -> None:
        self.carts: dict[str, dict[str, int]] = {}

    async def items(self, user_id: str) -> dict[str, int]:
        return dict(self.carts.get(user_id, {}))

    async def add(self, user_id: str, product_id: str, quantity: int) -> bool:
        cart = self.carts.setdefault(user_id, {})
        if cart.get(product_id, 0) + quantity > MAX_CART_QUANTITY:
            return False
        cart[product_id] = cart.get(product_id, 0) + quantity
        return True

    async def remove(self, user_id: str, product_id: str) -> bool:
        return self.carts.get(user_id, {}).pop(product_id, None) is not None

    async def clear(self, user_id: str) -> None:
        self.carts.pop(user_id, None)


class FakeIdempotency(IdempotencyKeys):
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], IdempotencyRecord] = {}
        self.ttls: dict[tuple[str, str], int] = {}

    async def get(self, user_id: str, key: str) -> IdempotencyRecord | None:
        return self.records.get((user_id, key))

    async def claim(self, user_id: str, key: str, order_id: str) -> bool:
        if (user_id, key) in self.records:
            return False
        self.records[user_id, key] = IdempotencyRecord(order_id, pending=True)
        return True

    async def commit(self, user_id: str, key: str, order_id: str, ttl_seconds: int) -> bool:
        if self.records.get((user_id, key)) != IdempotencyRecord(order_id, pending=True):
            return False
        self.records[user_id, key] = IdempotencyRecord(order_id, pending=False)
        self.ttls[user_id, key] = ttl_seconds
        return True

    async def forget(self, user_id: str, key: str, record: IdempotencyRecord) -> None:
        if self.records.get((user_id, key)) == record:
            del self.records[user_id, key]


def product(product_id: str, name: str, price_kopecks: int, stock: int = 10) -> catalog_pb2.Product:
    return catalog_pb2.Product(
        product_id=product_id, name=name, price_kopecks=price_kopecks, stock=stock
    )


class FakeCatalog(CatalogClient):
    def __init__(self, products: Iterable[catalog_pb2.Product] = ()) -> None:
        self.products = {item.product_id: item for item in products}
        # Исключение, которое бросит следующий вызов (например, DependencyUnavailable)
        self.error: Exception | None = None

    async def get_product(self, product_id: str) -> catalog_pb2.Product | None:
        if self.error is not None:
            raise self.error
        return self.products.get(product_id)


class FakeStock(StockClient):
    """StockService в памяти: остатки по товарам, резервы по order_id."""

    def __init__(self, available: Mapping[str, int] | None = None) -> None:
        self.available = dict(available or {})
        self.reserved: dict[str, dict[str, int]] = {}
        self.reserve_calls: list[tuple[str, dict[str, int]]] = []
        self.released: list[str] = []
        self.quietly_released: list[str] = []
        self.error: Exception | None = None

    async def reserve(self, order_id: str, items: Mapping[str, int]) -> None:
        self.reserve_calls.append((order_id, dict(items)))
        if self.error is not None:
            raise self.error
        if order_id in self.reserved:
            return
        violations = [
            PreconditionViolation(
                "INSUFFICIENT_STOCK",
                f"product:{product_id}",
                f"requested {quantity}, available {self.available.get(product_id, 0)}",
            )
            for product_id, quantity in items.items()
            if self.available.get(product_id, 0) < quantity
        ]
        if violations:
            raise FailedPrecondition(violations, message="Not enough stock")
        for product_id, quantity in items.items():
            self.available[product_id] -= quantity
        self.reserved[order_id] = dict(items)

    async def release(self, order_id: str, *, deadline: float | None = None) -> bool:
        if self.error is not None:
            raise self.error
        self.released.append(order_id)
        items = self.reserved.pop(order_id, None)
        for product_id, quantity in (items or {}).items():
            self.available[product_id] += quantity
        return items is not None

    async def release_quietly(self, order_id: str) -> None:
        self.quietly_released.append(order_id)


class FakeSubscription(Subscription):
    def __init__(self, queue: "asyncio.Queue[StatusChange]") -> None:
        self._queue = queue

    async def next(self, wait_s: float) -> StatusChange | None:
        try:
            return await asyncio.wait_for(self._queue.get(), wait_s)
        except TimeoutError:
            return None


class FakeEvents(OrderEvents):
    """Redis pub/sub в памяти: у каждой подписки своя очередь."""

    def __init__(self) -> None:
        self.published: list[StatusChange] = []
        self.subscribers: dict[str, list[asyncio.Queue[StatusChange]]] = {}
        # Вызывается сразу после подписки — чтобы сменить статус между подпиской и чтением из БД
        self.on_subscribe: Callable[[str], Awaitable[object]] | None = None
        self.error: Exception | None = None

    async def publish(self, change: StatusChange) -> None:
        if self.error is not None:
            raise self.error
        self.published.append(change)
        for queue in self.subscribers.get(change.order_id, []):
            queue.put_nowait(change)

    @asynccontextmanager
    async def subscribe(self, order_id: str) -> AsyncIterator[Subscription]:
        queue: asyncio.Queue[StatusChange] = asyncio.Queue()
        self.subscribers.setdefault(order_id, []).append(queue)
        try:
            if self.on_subscribe is not None:
                await self.on_subscribe(order_id)
            yield FakeSubscription(queue)
        finally:
            self.subscribers[order_id].remove(queue)
