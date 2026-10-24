"""Ошибки gRPC → HTTP: код по таблице google.rpc.Code, тело с кодом, сообщением и details."""

from collections.abc import Iterable
from typing import Any

import grpc
import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.protobuf import any_pb2, json_format
from stand_core.grpc import StandError
from stand_core.grpc.errors import error_status

logger = structlog.get_logger(__name__)

# Канонический HTTP-код каждого статуса (google/rpc/code.proto)
HTTP_STATUS: dict[grpc.StatusCode, int] = {
    grpc.StatusCode.OK: 200,
    grpc.StatusCode.CANCELLED: 499,
    grpc.StatusCode.UNKNOWN: 500,
    grpc.StatusCode.INVALID_ARGUMENT: 400,
    grpc.StatusCode.DEADLINE_EXCEEDED: 504,
    grpc.StatusCode.NOT_FOUND: 404,
    grpc.StatusCode.ALREADY_EXISTS: 409,
    grpc.StatusCode.PERMISSION_DENIED: 403,
    grpc.StatusCode.UNAUTHENTICATED: 401,
    grpc.StatusCode.RESOURCE_EXHAUSTED: 429,
    grpc.StatusCode.FAILED_PRECONDITION: 400,
    grpc.StatusCode.ABORTED: 409,
    grpc.StatusCode.OUT_OF_RANGE: 400,
    grpc.StatusCode.UNIMPLEMENTED: 501,
    grpc.StatusCode.INTERNAL: 500,
    grpc.StatusCode.UNAVAILABLE: 503,
    grpc.StatusCode.DATA_LOSS: 500,
}


def http_status(code: grpc.StatusCode) -> int:
    return HTTP_STATUS.get(code, 500)


def detail_json(detail: any_pb2.Any) -> dict[str, Any]:
    """Деталь google.rpc в JSON с `@type`; неизвестный тип — только `@type`."""
    try:
        return json_format.MessageToDict(detail, preserving_proto_field_name=True)
    except TypeError:
        return {"@type": detail.type_url}


def error_response(
    code: grpc.StatusCode, message: str, details: Iterable[any_pb2.Any] = ()
) -> JSONResponse:
    headers = {"www-authenticate": "Bearer"} if code is grpc.StatusCode.UNAUTHENTICATED else None
    body = {
        "error": {
            "code": code.name,
            "message": message,
            "details": [detail_json(detail) for detail in details],
        }
    }
    return JSONResponse(body, status_code=http_status(code), headers=headers)


async def rpc_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Ошибка ответа сервиса: его код, сообщение и rich details как есть."""
    assert isinstance(exc, grpc.aio.AioRpcError)
    code = exc.code()
    status = error_status(exc)
    details = [] if status is None else list(status.details)
    logger.info("upstream_error", path=request.url.path, grpc_status=code.name)
    return error_response(code, exc.details() or "", details)


async def stand_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Доменная ошибка stand_core; на gateway это `DependencyUnavailable` от базового клиента."""
    assert isinstance(exc, StandError)
    details = []
    for message in exc.details():
        packed = any_pb2.Any()
        packed.Pack(message)
        details.append(packed)
    logger.warning("gateway_error", path=request.url.path, grpc_status=exc.code.name)
    return error_response(exc.code, exc.message, details)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(grpc.aio.AioRpcError, rpc_error_handler)
    app.add_exception_handler(StandError, stand_error_handler)
