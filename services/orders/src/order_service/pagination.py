"""Пагинация списков order-service: те же правила и формат токена, что у catalog-service."""

import base64
import binascii
import json

from stand_core.grpc import FieldViolation, InvalidArgument

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
# Смещение уходит в Postgres OFFSET (bigint): больше — битый токен, а не ошибка базы
MAX_PAGE_OFFSET = 2**63 - 1


def encode_page_token(offset: int) -> str:
    """Непрозрачный для клиента токен: base64url от JSON со смещением."""
    return base64.urlsafe_b64encode(json.dumps({"offset": offset}).encode()).decode()


def decode_page_token(token: str) -> int:
    """Смещение из токена; пустой токен — первая страница, битый — INVALID_ARGUMENT."""
    if not token:
        return 0
    try:
        data = json.loads(base64.urlsafe_b64decode(token.encode("ascii")))
        offset = data["offset"]
    except (ValueError, TypeError, KeyError, binascii.Error):
        offset = None
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or not 0 <= offset <= MAX_PAGE_OFFSET
    ):
        raise InvalidArgument([FieldViolation("pagination.page_token", "invalid page token")])
    return offset


def page_size(requested: int) -> int:
    if requested < 0:
        raise InvalidArgument([FieldViolation("pagination.page_size", "must not be negative")])
    return min(requested or DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
