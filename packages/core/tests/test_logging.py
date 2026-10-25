import json

import pytest
from stand_core.logging import MASK, configure_logging, get_logger, mask_secrets


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "new_password",
        "access_token",
        "token",
        "code",
        "authorization",
        "x-api-key",
        "Authorization",
        "session_token",
    ],
)
def test_secret_keys_are_masked(key: str) -> None:
    assert mask_secrets({key: "s3cr3t"}) == {key: MASK}


def test_regular_keys_are_kept() -> None:
    data = {"email": "a@b.c", "currency_code": "RUB", "status": "OK", "count": 3}

    assert mask_secrets(data) == data


def test_nested_structures_and_metadata_pairs() -> None:
    data = {
        "request": {"email": "a@b.c", "password": "p", "items": [{"token": "t"}]},
        "metadata": [("authorization", "Bearer abc"), ("x-request-id", "r1")],
    }

    assert mask_secrets(data) == {
        "request": {"email": "a@b.c", "password": MASK, "items": [{"token": MASK}]},
        "metadata": [("authorization", MASK), ("x-request-id", "r1")],
    }


def test_bearer_inside_free_text_is_masked() -> None:
    assert mask_secrets("header was Bearer abc.def") == f"header was Bearer {MASK}"


def test_log_line_is_json_with_secrets_masked(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")

    get_logger("test").info(
        "rpc", method="/users.v1.UserService/SignIn", password="hunter2", code="123456"
    )

    line = capsys.readouterr().out.strip()
    record = json.loads(line)
    assert record["event"] == "rpc"
    assert record["level"] == "info"
    assert record["method"] == "/users.v1.UserService/SignIn"
    assert record["password"] == MASK
    assert record["code"] == MASK
    assert "hunter2" not in line
    assert "123456" not in line


def test_level_filter(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING")

    get_logger().info("hidden")
    get_logger().warning("shown")

    out = capsys.readouterr().out
    assert "hidden" not in out
    assert "shown" in out
