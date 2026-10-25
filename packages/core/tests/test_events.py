import json

import pytest
from stand_core.events import (
    USER_EMAIL_CONFIRMATION_REQUESTED,
    EmailConfirmationRequested,
    InvalidEvent,
    email_confirmation_payload,
    parse_email_confirmation,
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
