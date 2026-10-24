import asyncio

import pytest
from stand_core.grpc.context import (
    CurrentUser,
    Role,
    current_user,
    current_user_or_none,
    request_id,
    reset_current_user,
    reset_request_id,
    set_current_user,
    set_request_id,
)
from stand_core.grpc.errors import Unauthenticated


def test_defaults_are_empty() -> None:
    assert request_id() is None
    assert current_user_or_none() is None


def test_current_user_without_user_is_unauthenticated() -> None:
    with pytest.raises(Unauthenticated):
        current_user()


def test_set_and_reset() -> None:
    user = CurrentUser(id="u-1", role=Role.SELLER)
    rid_token = set_request_id("req-1")
    user_token = set_current_user(user)

    assert request_id() == "req-1"
    assert current_user() == user

    reset_current_user(user_token)
    reset_request_id(rid_token)
    assert request_id() is None
    assert current_user_or_none() is None


async def test_values_are_isolated_between_tasks() -> None:
    async def handle(rid: str, user_id: str) -> tuple[str | None, str]:
        set_request_id(rid)
        set_current_user(CurrentUser(id=user_id, role=Role.BUYER))
        await asyncio.sleep(0)
        return request_id(), current_user().id

    results = await asyncio.gather(handle("r-1", "u-1"), handle("r-2", "u-2"))

    assert list(results) == [("r-1", "u-1"), ("r-2", "u-2")]
    assert request_id() is None
