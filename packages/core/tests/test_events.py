import json
from datetime import UTC, datetime

import pytest
from stand_core.events import (
    ORDER_STATUS_CHANGED,
    USER_EMAIL_CONFIRMATION_REQUESTED,
    EmailConfirmationRequested,
    InvalidEvent,
    OrderStatusChanged,
    email_confirmation_payload,
    order_status_changed_payload,
    parse_email_confirmation,
    parse_order_status_changed,
)

EVENT = EmailConfirmationRequested(
    email="buyer@example.com", code="123456", display_name="Юля", ttl_s=900, request_id="req-1"
)


def test_routing_key() -> None:
    assert USER_EMAIL_CONFIRMATION_REQUESTED == "user.email_confirmation_requested"


def test_payload_roundtrip_through_json() -> None:
    payload = email_confirmation_payload(EVENT)

    assert payload == {
        "email": "buyer@example.com",
        "code": "123456",
        "display_name": "Юля",
        "ttl_s": 900,
        "request_id": "req-1",
    }
    assert parse_email_confirmation(json.dumps(payload).encode()) == EVENT
    assert parse_email_confirmation(json.dumps(payload)) == EVENT
    assert parse_email_confirmation(payload) == EVENT


def test_extra_fields_are_ignored() -> None:
    payload = {**email_confirmation_payload(EVENT), "locale": "ru", "version": 2}

    assert parse_email_confirmation(payload) == EVENT


def test_request_id_is_optional() -> None:
    payload = email_confirmation_payload(EVENT)
    del payload["request_id"]

    assert parse_email_confirmation(payload).request_id is None


@pytest.mark.parametrize("name", ["email", "code", "display_name", "ttl_s"])
def test_missing_field(name: str) -> None:
    payload = email_confirmation_payload(EVENT)
    del payload[name]

    with pytest.raises(InvalidEvent, match=f"'{name}' is missing"):
        parse_email_confirmation(payload)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("email", ""),
        ("email", 1),
        ("code", None),
        ("ttl_s", "900"),
        ("ttl_s", 0),
        ("ttl_s", True),
        ("request_id", 5),
    ],
)
def test_wrong_type(name: str, value: object) -> None:
    payload = {**email_confirmation_payload(EVENT), name: value}

    with pytest.raises(InvalidEvent, match=f"'{name}' must be"):
        parse_email_confirmation(payload)


@pytest.mark.parametrize("body", [b"not json", b"\xff\xfe", b"[1, 2]", b'"str"'])
def test_body_is_not_json_object(body: bytes) -> None:
    with pytest.raises(InvalidEvent, match="JSON"):
        parse_email_confirmation(body)


def test_order_status_changed_routing_key() -> None:
    assert ORDER_STATUS_CHANGED == "order.status_changed"


def test_order_status_changed_roundtrip() -> None:
    changed_at = datetime(2026, 10, 26, 12, 0, 1, tzinfo=UTC)
    event = OrderStatusChanged(
        order_id="o-1",
        user_id="u-1",
        status="DELIVERED",
        changed_at=changed_at,
        email="buyer@example.com",
        request_id="r-1",
    )

    payload = order_status_changed_payload(event)

    assert payload["changed_at"] == changed_at.isoformat()
    assert parse_order_status_changed(json.dumps(payload).encode()) == event


def test_order_status_changed_email_is_optional() -> None:
    payload = {
        "order_id": "o-1",
        "user_id": "u-1",
        "status": "DELIVERED",
        "changed_at": "2026-10-26T12:00:01+00:00",
    }

    event = parse_order_status_changed(payload)

    assert event.email == ""
    assert event.request_id is None


def test_order_status_changed_empty_email_roundtrip() -> None:
    event = OrderStatusChanged(
        order_id="o-1",
        user_id="u-1",
        status="DELIVERED",
        changed_at=datetime(2026, 10, 26, 12, 0, 1, tzinfo=UTC),
    )

    assert parse_order_status_changed(json.dumps(order_status_changed_payload(event))) == event


@pytest.mark.parametrize(
    "payload",
    [
        {"user_id": "u-1", "status": "PAID", "changed_at": "2026-10-26T12:00:01+00:00"},
        {"order_id": "o-1", "status": "PAID", "changed_at": "2026-10-26T12:00:01+00:00"},
        {"order_id": "o-1", "user_id": "u-1", "changed_at": "2026-10-26T12:00:01+00:00"},
        {"order_id": "o-1", "user_id": "u-1", "status": "PAID", "changed_at": "не дата"},
        {"order_id": "o-1", "user_id": "u-1", "status": "PAID", "changed_at": 1700000000},
        {"order_id": "o-1", "user_id": "u-1", "status": "PAID"},
        {
            "order_id": "o-1",
            "user_id": "u-1",
            "status": "PAID",
            "changed_at": "2026-10-26T12:00:01+00:00",
            "email": 42,
        },
    ],
)
def test_order_status_changed_invalid(payload: dict[str, object]) -> None:
    with pytest.raises(InvalidEvent):
        parse_order_status_changed(payload)
