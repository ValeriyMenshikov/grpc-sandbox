import asyncio
import uuid
from collections.abc import Mapping

from orders.v1 import orders_pb2
from stand_core import Context, rpc
from stand_core.grpc import (
    DependencyUnavailable,
    FailedPrecondition,
    FieldViolation,
    InvalidArgument,
    PreconditionViolation,
    current_user,
    metadata_value,
)

from order_service.carts import Carts
from order_service.catalog_client import CatalogClient
from order_service.convert import order_pb
from order_service.idempotency import IdempotencyKeys, IdempotencyRecord
from order_service.models import Order, OrderItem
from order_service.repository import OrderRepository
from order_service.settings import OrderSettings
from order_service.stock_client import StockClient

IDEMPOTENCY_HEADER = "idempotency-key"
MAX_IDEMPOTENCY_KEY_LENGTH = 128


def idempotency_key(context: Context) -> str:
    key = (metadata_value(context, IDEMPOTENCY_HEADER) or "").strip()
    if not key:
        raise InvalidArgument([FieldViolation(IDEMPOTENCY_HEADER, "metadata is required")])
    if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise InvalidArgument(
            [FieldViolation(IDEMPOTENCY_HEADER, f"must be at most {MAX_IDEMPOTENCY_KEY_LENGTH}")]
        )
    return key


async def replayed_order(
    user_id: str, key: str, idempotency: IdempotencyKeys, repository: OrderRepository
) -> Order | None:
    """Заказ, уже оформленный с этим ключом; None — ключ свободен."""
    record = await idempotency.get(user_id, key)
    if record is None:
        return None
    if record.pending:
        raise FailedPrecondition(
            [
                PreconditionViolation(
                    "CHECKOUT_IN_PROGRESS",
                    f"{IDEMPOTENCY_HEADER}:{key}",
                    "checkout with this key is in progress, retry later",
                )
            ],
            message="Checkout with this idempotency key is in progress",
        )
    order = await repository.get_order(record.order_id)
    if order is None:
        # Ключ пережил заказ (make reset очистил базу, но не Redis) — оформляем заново
        await idempotency.forget(user_id, key, record)
    return order


async def release_reserve(stock: StockClient, order_id: str) -> None:
    """Снять резерв так, чтобы отмена вызова (клиент ушёл, истёк deadline) его не оборвала."""
    await asyncio.shield(stock.release_quietly(order_id))


async def place_order(
    order_id: str,
    user_id: str,
    cart: Mapping[str, int],
    stock: StockClient,
    catalog: CatalogClient,
    repository: OrderRepository,
) -> Order:
    """Резерв в catalog → снимок цен → заказ CREATED; при неудаче после резерва резерв снимается."""
    try:
        # Нехватка и неизвестный товар — FailedPrecondition с деталями catalog, резерва нет
        await stock.reserve(order_id, cart)
    except (DependencyUnavailable, asyncio.CancelledError):
        # Catalog мог успеть зарезервировать, а ответ не дошёл до deadline или вызов отменён
        await release_reserve(stock, order_id)
        raise
    try:
        products = await catalog.get_products(cart)
        missing = [product_id for product_id in cart if product_id not in products]
        if missing:
            raise FailedPrecondition(
                [
                    PreconditionViolation(
                        "PRODUCT_NOT_FOUND", f"product:{product_id}", "product does not exist"
                    )
                    for product_id in missing
                ],
                message="Products not found",
            )
        items = [
            OrderItem(
                product_id, products[product_id].name, quantity, products[product_id].price_kopecks
            )
            for product_id, quantity in cart.items()
        ]
        return await repository.create_order(order_id, user_id, items)
    except BaseException:
        # BaseException: отмена (CancelledError) тоже не должна оставить резерв навсегда
        await release_reserve(stock, order_id)
        raise


@rpc("Checkout", package="orders.v1", service="OrderService")
async def checkout(
    request: orders_pb2.CheckoutRequest,
    context: Context,
    carts: Carts,
    idempotency: IdempotencyKeys,
    repository: OrderRepository,
    stock: StockClient,
    catalog: CatalogClient,
    settings: OrderSettings,
) -> orders_pb2.CheckoutResponse:
    key = idempotency_key(context)
    user_id = current_user().id
    # Повтор возвращает тот же заказ, даже если корзина с тех пор изменилась или опустела
    order = await replayed_order(user_id, key, idempotency, repository)
    if order is not None:
        return orders_pb2.CheckoutResponse(order=order_pb(order))

    cart = await carts.items(user_id)
    if not cart:
        raise FailedPrecondition(
            [PreconditionViolation("CART_EMPTY", f"cart:{user_id}", "add items before checkout")],
            message="Cart is empty",
        )
    # order_id выбираем сами: он же ключ идемпотентного резерва в catalog
    order_id = str(uuid.uuid4())
    if not await idempotency.claim(user_id, key, order_id):
        # Параллельный вызов с тем же ключом успел раньше
        order = await replayed_order(user_id, key, idempotency, repository)
        if order is None:
            raise FailedPrecondition(message="Idempotency key is busy, retry")
        return orders_pb2.CheckoutResponse(order=order_pb(order))
    try:
        order = await place_order(order_id, user_id, cart, stock, catalog, repository)
    except Exception:
        # Заказа нет — ключ свободен для повтора (если его ещё держит этот вызов)
        await idempotency.forget(user_id, key, IdempotencyRecord(order_id, pending=True))
        raise
    await idempotency.commit(user_id, key, order.order_id, settings.idempotency_ttl_s)
    await carts.clear(user_id)
    return orders_pb2.CheckoutResponse(order=order_pb(order))
