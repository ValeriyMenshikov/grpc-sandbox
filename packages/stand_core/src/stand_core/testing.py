"""Хелперы для тестов сервисов стенда.

`rich_status` — google.rpc.Status из ошибки grpc.aio с проверкой, что details есть и код совпадает.
"""

import grpc
from google.rpc import status_pb2

from stand_core.grpc.errors import DETAILS_KEY, error_status

__all__ = ("DETAILS_KEY", "rich_status")


def rich_status(error: grpc.aio.AioRpcError) -> status_pb2.Status:
    status = error_status(error)
    if status is None:
        raise AssertionError(f"{error.code()} has no {DETAILS_KEY}")
    assert status.code == error.code().value[0]
    return status
