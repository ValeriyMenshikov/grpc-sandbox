import pytest
from catalog_service.convert import kopecks_to_money, money_to_kopecks
from common.v1 import money_pb2


@pytest.mark.parametrize(
    ("kopecks", "units", "nanos"), [(1, 0, 10_000_000), (19_990, 199, 900_000_000), (500, 5, 0)]
)
def test_money_round_trip(kopecks: int, units: int, nanos: int) -> None:
    money = kopecks_to_money(kopecks)

    assert (money.currency_code, money.units, money.nanos) == ("RUB", units, nanos)
    assert money_to_kopecks(money, "price") == (kopecks, [])


@pytest.mark.parametrize(
    ("money", "field"),
    [
        (money_pb2.Money(units=-1), "price"),
        (money_pb2.Money(units=1, nanos=1_000_000_000), "price.nanos"),
        (money_pb2.Money(units=1, nanos=1), "price.nanos"),
        (money_pb2.Money(currency_code="EUR", units=1), "price.currency_code"),
    ],
)
def test_invalid_money(money: money_pb2.Money, field: str) -> None:
    kopecks, violations = money_to_kopecks(money, "price")

    assert kopecks is None
    assert [v.field for v in violations] == [field]
