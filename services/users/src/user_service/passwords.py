"""Хэширование паролей средствами stdlib (hashlib.scrypt), без внешних зависимостей.

Формат хэша: `scrypt$<n>$<r>$<p>$<salt base64>$<hash base64>` — параметры хранятся вместе с
хэшем, поэтому их можно поменять, не ломая старые пароли. Хэширование — CPU-bound (~16 МБ памяти
и десятки миллисекунд), поэтому асинхронные обёртки уводят его в поток.
"""

import asyncio
import base64
import hashlib
import hmac
import secrets

SCHEME = "scrypt"
# n * r * 128 байт = 16 МБ на хэш: укладывается в mem_limit контейнера
N = 2**14
R = 8
P = 1
SALT_BYTES = 16
KEY_BYTES = 32


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=n, r=r, p=p, maxmem=2 * 128 * n * r, dklen=KEY_BYTES
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    key = _scrypt(password, salt, N, R, P)
    encoded = [base64.b64encode(part).decode() for part in (salt, key)]
    return "$".join([SCHEME, str(N), str(R), str(P), *encoded])


def verify_password(password: str, password_hash: str) -> bool:
    """Совпадает ли пароль с хэшем; хэш в неизвестном формате — не совпадает."""
    try:
        scheme, n, r, p, salt, key = password_hash.split("$")
        if scheme != SCHEME:
            return False
        expected = base64.b64decode(key, validate=True)
        actual = _scrypt(password, base64.b64decode(salt, validate=True), int(n), int(r), int(p))
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    return await asyncio.to_thread(verify_password, password, password_hash)
