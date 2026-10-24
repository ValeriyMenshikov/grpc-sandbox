"""google.rpc.Status из ошибки grpc.aio (rpc_status.from_call типизирован только под grpc.Call)."""

import grpc
from google.rpc import status_pb2

DETAILS_KEY = "grpc-status-details-bin"


def rich_status(error: grpc.aio.AioRpcError) -> status_pb2.Status:
    for key, value in error.trailing_metadata() or ():
        if key == DETAILS_KEY and isinstance(value, bytes):
            status = status_pb2.Status.FromString(value)
            assert status.code == error.code().value[0]
            return status
    raise AssertionError(f"{error.code()} has no {DETAILS_KEY}")
