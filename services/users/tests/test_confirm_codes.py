from unittest.mock import AsyncMock, Mock

from user_service.confirm_codes import ConfirmCodes, confirm_key, generate_code


def test_codes_are_six_digits() -> None:
    codes = {generate_code() for _ in range(200)}
    assert all(len(code) == 6 and code.isdigit() for code in codes)
    assert len(codes) > 1


async def test_codes_live_under_confirm_key_with_ttl() -> None:
    redis = Mock()
    redis.client.set = AsyncMock()
    redis.client.get = AsyncMock(return_value="123456")
    redis.client.delete = AsyncMock()
    codes = ConfirmCodes(redis)

    await codes.save("a@b.c", "123456", 900)
    found = await codes.get("a@b.c")
    await codes.delete("a@b.c")

    assert confirm_key("a@b.c") == "confirm:a@b.c"
    redis.client.set.assert_awaited_once_with("confirm:a@b.c", "123456", ex=900)
    redis.client.get.assert_awaited_once_with("confirm:a@b.c")
    redis.client.delete.assert_awaited_once_with("confirm:a@b.c")
    assert found == "123456"


async def test_missing_code_is_none() -> None:
    redis = Mock()
    redis.client.get = AsyncMock(return_value=None)
    assert await ConfirmCodes(redis).get("a@b.c") is None
