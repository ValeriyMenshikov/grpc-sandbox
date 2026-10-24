import asyncio
import threading
import time

import pytest
from user_service import passwords
from user_service.passwords import (
    MAX_PARALLEL_HASHES,
    hash_password,
    hash_password_async,
    verify_password,
    verify_password_async,
)


def test_hash_verifies_only_the_same_password() -> None:
    password_hash = hash_password("s3cret-pass")

    assert password_hash.startswith("scrypt$")
    assert "s3cret-pass" not in password_hash
    assert verify_password("s3cret-pass", password_hash)
    assert not verify_password("s3cret-pasS", password_hash)


def test_same_password_gets_different_salt() -> None:
    assert hash_password("s3cret-pass") != hash_password("s3cret-pass")


def test_malformed_hash_does_not_verify() -> None:
    for broken in ["", "plain", "bcrypt$1$2$3$c2FsdA==$a2V5", "scrypt$x$8$1$c2FsdA==$a2V5"]:
        assert not verify_password("anything", broken)


async def test_async_wrappers() -> None:
    password_hash = await hash_password_async("s3cret-pass")
    assert await verify_password_async("s3cret-pass", password_hash)


async def test_parallel_hashes_are_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    """Всплеск запросов не считает больше MAX_PARALLEL_HASHES хэшей одновременно (память)."""
    running = 0
    peak = 0
    lock = threading.Lock()

    def slow_hash(password: str) -> str:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.02)
        with lock:
            running -= 1
        return password

    monkeypatch.setattr(passwords, "hash_password", slow_hash)
    await asyncio.gather(*(hash_password_async(str(i)) for i in range(MAX_PARALLEL_HASHES * 4)))

    assert peak == MAX_PARALLEL_HASHES
