"""Доменный Product ↔ сообщения catalog.v1 / catalog.v2, деньги ↔ копейки."""

from datetime import datetime

from catalog.v1 import catalog_pb2 as v1
from catalog.v2 import catalog_pb2 as v2
from common.v1 import money_pb2
from google.protobuf.timestamp_pb2 import Timestamp
from stand_core.grpc import FieldViolation

from catalog_service.models import Product

CURRENCY = "RUB"
NANOS_PER_KOPECK = 10_000_000
KOPECKS_PER_UNIT = 100


def _timestamp(value: datetime) -> Timestamp:
    timestamp = Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def product_v1(product: Product) -> v1.Product:
    return v1.Product(
        product_id=product.product_id,
        seller_id=product.seller_id,
        offer_id=product.offer_id,
        name=product.name,
        category=product.category,
        price_kopecks=product.price_kopecks,
        stock=product.stock,
        created_at=_timestamp(product.created_at),
        updated_at=_timestamp(product.updated_at),
    )


def product_v2(product: Product) -> v2.Product:
    return v2.Product(
        product_id=product.product_id,
        seller_id=product.seller_id,
        offer_id=product.offer_id,
        name=product.name,
        category=product.category,
        stock=product.stock,
        created_at=_timestamp(product.created_at),
        updated_at=_timestamp(product.updated_at),
        price=kopecks_to_money(product.price_kopecks),
    )


def kopecks_to_money(kopecks: int) -> money_pb2.Money:
    units, rest = divmod(kopecks, KOPECKS_PER_UNIT)
    return money_pb2.Money(currency_code=CURRENCY, units=units, nanos=rest * NANOS_PER_KOPECK)


def money_to_kopecks(money: money_pb2.Money, field: str) -> tuple[int | None, list[FieldViolation]]:
    """Сумма в копейках; цена не бывает отрицательной и точнее копейки, валюта — только RUB."""
    violations: list[FieldViolation] = []
    if money.currency_code not in ("", CURRENCY):
        violations.append(FieldViolation(f"{field}.currency_code", f"only {CURRENCY} is supported"))
    if money.units < 0 or money.nanos < 0:
        violations.append(FieldViolation(field, "must not be negative"))
    elif money.nanos >= 1_000_000_000 or money.nanos % NANOS_PER_KOPECK:
        violations.append(FieldViolation(f"{field}.nanos", "must be whole kopecks below 1e9"))
    if violations:
        return None, violations
    return money.units * KOPECKS_PER_UNIT + money.nanos // NANOS_PER_KOPECK, []
