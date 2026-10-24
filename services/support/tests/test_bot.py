from orders.v1 import orders_pb2
from support_service.bot import STATUS_TEXT, STATUS_UNAVAILABLE, is_status_question, status_reply

from .fakes import order


def test_triggers_ignore_case() -> None:
    assert is_status_question("Какой СТАТУС у заказа?")
    assert is_status_question("Где посылка")
    assert not is_status_question("Спасибо!")


def test_every_status_has_text() -> None:
    known = set(orders_pb2.OrderStatus.values()) - {orders_pb2.ORDER_STATUS_UNSPECIFIED}
    assert set(STATUS_TEXT) == known


def test_reply_names_order_and_status() -> None:
    assert status_reply(order("o-1")) == "Заказ o-1: передан курьеру"
    assert status_reply(order("o-1", status=orders_pb2.ORDER_STATUS_UNSPECIFIED)) == (
        STATUS_UNAVAILABLE
    )
