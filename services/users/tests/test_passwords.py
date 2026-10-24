from user_service.passwords import (
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
