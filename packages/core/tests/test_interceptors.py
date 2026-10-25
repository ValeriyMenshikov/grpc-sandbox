"""Цепочка интерцепторов стенда на поднятом in-process сервере (все четыре типа вызовов)."""

from collections.abc import AsyncIterator
from typing import Any

import grpc
import pytest
from catalog.v1 import catalog_pb2
from google.rpc import error_details_pb2
from grpc_health.v1 import health_pb2
from stand_core import Context
from stand_core.clients.sessions import Sessions
from stand_core.grpc.context import CurrentUser, Role, authorization, current_user, request_id
from stand_core.grpc.errors import (
    FailedPrecondition,
    FieldViolation,
    InvalidArgument,
    NotFound,
    PreconditionViolation,
    StandError,
)
from stand_core.grpc.interceptors import (
    AuthInterceptor,
    AuthPolicy,
    ExceptionHandlingInterceptor,
    LoggingInterceptor,
    RequestIdInterceptor,
    StreamCountInterceptor,
    register_auth_policies,
)
from stand_core.grpc.rpc import MethodAnnotation, MethodSignature, annotate
from stand_core.grpc.server import RunningServer, grpc_server
from stand_core.settings import Settings
from stand_core.testing import rich_status
from structlog.testing import capture_logs
from support.v1 import support_pb2

API_KEY = "test-key"
BUYER_TOKEN = "buyer-token"
SELLER_TOKEN = "seller-token"
CATALOG = "/catalog.v1.CatalogService"
CHAT = "/support.v1.SupportService/Chat"

ERRORS: dict[str, StandError] = {
    "not_found": NotFound("product", "p404"),
    "bad": InvalidArgument([FieldViolation("product_id", "must not be empty")]),
    "precondition": FailedPrecondition([PreconditionViolation("STOCK", "p1", "not enough")]),
}


# Токен, на котором хранилище сессий падает (как недоступный Redis)
BROKEN_TOKEN = "broken-token"


class FakeSessions(Sessions):
    """Сессии без Redis: токен → пользователь."""

    def __init__(self) -> None:
        self.users = {
            BUYER_TOKEN: CurrentUser("buyer-1", Role.BUYER),
            SELLER_TOKEN: CurrentUser("seller-1", Role.SELLER),
        }

    async def get(self, token: str) -> CurrentUser | None:
        if token == BROKEN_TOKEN:
            raise ConnectionError("redis:6379 refused")
        return self.users.get(token)


async def get_product(
    request: catalog_pb2.GetProductRequest, context: Context
) -> catalog_pb2.GetProductResponse:
    if request.product_id in ERRORS:
        raise ERRORS[request.product_id]
    if request.product_id == "boom":
        raise RuntimeError("secret internals")
    if request.product_id == "abort":
        await context.abort(grpc.StatusCode.UNKNOWN, "Validation failed")
    user = current_user()
    return catalog_pb2.GetProductResponse(
        product=catalog_pb2.Product(
            product_id=request_id() or "",
            seller_id=user.id,
            name=authorization() or "",
        )
    )


async def import_products(
    request: AsyncIterator[catalog_pb2.ImportProductsRequest], context: Context
) -> catalog_pb2.ImportProductsResponse:
    created = 0
    async for message in request:
        if message.WhichOneof("payload") == "row":
            created += 1
    return catalog_pb2.ImportProductsResponse(created=created)


async def export_products(
    request: catalog_pb2.ExportProductsRequest, context: Context
) -> AsyncIterator[catalog_pb2.ExportProductsResponse]:
    for index in range(3):
        yield catalog_pb2.ExportProductsResponse(
            product=catalog_pb2.Product(product_id=f"p{index}", seller_id=current_user().id)
        )
    context.set_trailing_metadata((("x-close-reason", "done"),))


async def chat(
    request: AsyncIterator[support_pb2.ChatRequest], context: Context
) -> AsyncIterator[support_pb2.ChatResponse]:
    async for message in request:
        if message.message.text == "fail":
            raise NotFound("order", "o1")
        yield support_pb2.ChatResponse(
            ack=support_pb2.Ack(client_message_id=message.message.client_message_id)
        )


def handlers() -> dict[MethodSignature, MethodAnnotation]:
    catalog = ("CatalogService", "catalog.v1")
    return {
        MethodSignature("GetProduct", *catalog): annotate(get_product),
        MethodSignature("ImportProducts", *catalog): annotate(import_products),
        MethodSignature("ExportProducts", *catalog): annotate(export_products),
        MethodSignature("Chat", "SupportService", "support.v1"): annotate(chat),
    }


@pytest.fixture
async def running(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[RunningServer]:
    monkeypatch.setenv("STAND_API_KEY", API_KEY)
    register_auth_policies(
        {
            f"{CATALOG}/GetProduct": AuthPolicy.USER,
            f"{CATALOG}/ImportProducts": AuthPolicy.SERVICE,
            f"{CATALOG}/ExportProducts": AuthPolicy.SELLER,
            # Chat — без строки в таблице: политика по умолчанию (user)
        }
    )
    interceptors = [
        RequestIdInterceptor(),
        LoggingInterceptor(),
        AuthInterceptor(Settings(), FakeSessions()),
        StreamCountInterceptor(),
        ExceptionHandlingInterceptor(),
    ]
    async with grpc_server(handlers(), interceptors, port=0, host="localhost", grace=0) as server:
        yield server


@pytest.fixture
async def channel(running: RunningServer) -> AsyncIterator[grpc.aio.Channel]:
    async with grpc.aio.insecure_channel(f"localhost:{running.port}") as channel:
        yield channel


def auth(token: str | None = BUYER_TOKEN, api_key: str | None = API_KEY) -> list[tuple[str, str]]:
    metadata = []
    if api_key is not None:
        metadata.append(("x-api-key", api_key))
    if token is not None:
        metadata.append(("authorization", f"Bearer {token}"))
    return metadata


def unary(channel: grpc.aio.Channel) -> Any:
    return channel.unary_unary(
        f"{CATALOG}/GetProduct",
        request_serializer=catalog_pb2.GetProductRequest.SerializeToString,
        response_deserializer=catalog_pb2.GetProductResponse.FromString,
    )


def export(channel: grpc.aio.Channel) -> Any:
    return channel.unary_stream(
        f"{CATALOG}/ExportProducts",
        request_serializer=catalog_pb2.ExportProductsRequest.SerializeToString,
        response_deserializer=catalog_pb2.ExportProductsResponse.FromString,
    )


def chat_call(channel: grpc.aio.Channel) -> Any:
    return channel.stream_stream(
        CHAT,
        request_serializer=support_pb2.ChatRequest.SerializeToString,
        response_deserializer=support_pb2.ChatResponse.FromString,
    )


def chat_messages(*texts: str) -> list[support_pb2.ChatRequest]:
    return [
        support_pb2.ChatRequest(
            message=support_pb2.ClientMessage(client_message_id=f"c{index}", text=text)
        )
        for index, text in enumerate(texts)
    ]


async def get_error(call: Any) -> grpc.aio.AioRpcError:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await call
    return info.value


# --- RequestIdInterceptor ---


async def test_request_id_is_taken_from_metadata(channel: grpc.aio.Channel) -> None:
    call = unary(channel)(
        catalog_pb2.GetProductRequest(product_id="p1"),
        metadata=[*auth(), ("x-request-id", "rid-42")],
    )

    response = await call

    assert dict(await call.initial_metadata())["x-request-id"] == "rid-42"
    # Хэндлер видит тот же request_id в contextvar
    assert response.product.product_id == "rid-42"


async def test_request_id_is_generated(channel: grpc.aio.Channel) -> None:
    call = unary(channel)(catalog_pb2.GetProductRequest(product_id="p1"), metadata=auth())

    response = await call

    generated = dict(await call.initial_metadata())["x-request-id"]
    assert len(str(generated)) == 36
    assert response.product.product_id == generated


async def test_request_id_is_sent_on_error(channel: grpc.aio.Channel) -> None:
    call = unary(channel)(
        catalog_pb2.GetProductRequest(product_id="not_found"),
        metadata=[*auth(), ("x-request-id", "rid-err")],
    )

    await get_error(call)

    assert dict(await call.initial_metadata())["x-request-id"] == "rid-err"


async def test_request_id_on_stream(channel: grpc.aio.Channel) -> None:
    call = export(channel)(
        catalog_pb2.ExportProductsRequest(),
        metadata=[*auth(SELLER_TOKEN), ("x-request-id", "rid-stream")],
    )

    _ = [message async for message in call]

    assert dict(await call.initial_metadata())["x-request-id"] == "rid-stream"


# --- StreamCountInterceptor ---


async def test_items_count_on_server_stream_keeps_handler_trailers(
    channel: grpc.aio.Channel,
) -> None:
    call = export(channel)(catalog_pb2.ExportProductsRequest(), metadata=auth(SELLER_TOKEN))

    messages = [message async for message in call]

    trailers = dict(await call.trailing_metadata())
    assert len(messages) == 3
    assert trailers["x-items-count"] == "3"
    assert trailers["x-close-reason"] == "done"


async def test_items_count_on_bidi(channel: grpc.aio.Channel) -> None:
    call = chat_call(channel)(iter(chat_messages("a", "b")), metadata=auth())

    acks = [response.ack.client_message_id async for response in call]

    assert acks == ["c0", "c1"]
    assert dict(await call.trailing_metadata())["x-items-count"] == "2"


async def test_no_items_count_on_unary(channel: grpc.aio.Channel) -> None:
    call = unary(channel)(catalog_pb2.GetProductRequest(product_id="p1"), metadata=auth())

    await call

    assert "x-items-count" not in dict(await call.trailing_metadata())


# --- ExceptionHandlingInterceptor ---


@pytest.mark.parametrize(
    ("product_id", "code", "detail_type"),
    [
        ("not_found", grpc.StatusCode.NOT_FOUND, error_details_pb2.ResourceInfo),
        ("bad", grpc.StatusCode.INVALID_ARGUMENT, error_details_pb2.BadRequest),
        (
            "precondition",
            grpc.StatusCode.FAILED_PRECONDITION,
            error_details_pb2.PreconditionFailure,
        ),
    ],
)
async def test_domain_error_gives_status_and_details(
    channel: grpc.aio.Channel,
    product_id: str,
    code: grpc.StatusCode,
    detail_type: type[Any],
) -> None:
    error = await get_error(
        unary(channel)(catalog_pb2.GetProductRequest(product_id=product_id), metadata=auth())
    )

    assert error.code() is code
    status = rich_status(error)
    assert status.message == ERRORS[product_id].message
    assert [detail.Is(detail_type.DESCRIPTOR) for detail in status.details] == [True]


async def test_unexpected_error_is_internal_without_details(channel: grpc.aio.Channel) -> None:
    with capture_logs() as logs:
        error = await get_error(
            unary(channel)(catalog_pb2.GetProductRequest(product_id="boom"), metadata=auth())
        )

    assert error.code() is grpc.StatusCode.INTERNAL
    assert error.details() == "Internal error"
    assert "secret internals" not in str(error.debug_error_string())
    # Стек — только в лог
    unhandled = [log for log in logs if log["event"] == "grpc.unhandled_exception"]
    assert unhandled
    assert unhandled[0]["exc_info"] is True


async def test_handler_abort_passes_through(channel: grpc.aio.Channel) -> None:
    error = await get_error(
        unary(channel)(catalog_pb2.GetProductRequest(product_id="abort"), metadata=auth())
    )

    assert error.code() is grpc.StatusCode.UNKNOWN
    assert error.details() == "Validation failed"


async def test_domain_error_in_bidi_stream(channel: grpc.aio.Channel) -> None:
    call = chat_call(channel)(iter(chat_messages("a", "fail")), metadata=auth())

    with pytest.raises(grpc.aio.AioRpcError) as info:
        _ = [response async for response in call]

    assert info.value.code() is grpc.StatusCode.NOT_FOUND
    resource = error_details_pb2.ResourceInfo()
    assert rich_status(info.value).details[0].Unpack(resource)
    assert (resource.resource_type, resource.resource_name) == ("order", "o1")


# --- AuthInterceptor ---


@pytest.mark.parametrize("api_key", [None, "wrong-key"])
async def test_missing_or_wrong_api_key_is_unauthenticated(
    channel: grpc.aio.Channel, api_key: str | None
) -> None:
    error = await get_error(
        unary(channel)(
            catalog_pb2.GetProductRequest(product_id="p1"), metadata=auth(api_key=api_key)
        )
    )

    assert error.code() is grpc.StatusCode.UNAUTHENTICATED


async def test_missing_api_key_on_service_method(channel: grpc.aio.Channel) -> None:
    call = channel.stream_unary(
        f"{CATALOG}/ImportProducts",
        request_serializer=catalog_pb2.ImportProductsRequest.SerializeToString,
        response_deserializer=catalog_pb2.ImportProductsResponse.FromString,
    )

    error = await get_error(call(iter([catalog_pb2.ImportProductsRequest()])))

    assert error.code() is grpc.StatusCode.UNAUTHENTICATED


async def test_service_method_needs_only_api_key(channel: grpc.aio.Channel) -> None:
    call = channel.stream_unary(
        f"{CATALOG}/ImportProducts",
        request_serializer=catalog_pb2.ImportProductsRequest.SerializeToString,
        response_deserializer=catalog_pb2.ImportProductsResponse.FromString,
    )
    rows = [
        catalog_pb2.ImportProductsRequest(header=catalog_pb2.ImportHeader()),
        catalog_pb2.ImportProductsRequest(row=catalog_pb2.ImportRow(offer_id="a")),
    ]

    response = await call(iter(rows), metadata=auth(token=None))

    assert response.created == 1


@pytest.mark.parametrize("token", [None, "unknown-token"])
async def test_user_method_without_valid_token_is_unauthenticated(
    channel: grpc.aio.Channel, token: str | None
) -> None:
    error = await get_error(
        unary(channel)(catalog_pb2.GetProductRequest(product_id="p1"), metadata=auth(token))
    )

    assert error.code() is grpc.StatusCode.UNAUTHENTICATED


async def test_broken_session_store_is_internal_without_internals(
    channel: grpc.aio.Channel,
) -> None:
    error = await get_error(
        unary(channel)(catalog_pb2.GetProductRequest(product_id="p1"), metadata=auth(BROKEN_TOKEN))
    )

    assert error.code() is grpc.StatusCode.INTERNAL
    assert error.details() == "Internal error"


async def test_user_method_without_policy_requires_user(channel: grpc.aio.Channel) -> None:
    call = chat_call(channel)(iter(chat_messages("a")), metadata=auth(token=None))

    with pytest.raises(grpc.aio.AioRpcError) as info:
        _ = [response async for response in call]

    assert info.value.code() is grpc.StatusCode.UNAUTHENTICATED


async def test_user_is_put_into_context(channel: grpc.aio.Channel) -> None:
    response = await unary(channel)(
        catalog_pb2.GetProductRequest(product_id="p1"), metadata=auth(BUYER_TOKEN)
    )

    assert response.product.seller_id == "buyer-1"
    assert response.product.name == f"Bearer {BUYER_TOKEN}"


async def test_buyer_on_seller_method_is_permission_denied(channel: grpc.aio.Channel) -> None:
    call = export(channel)(catalog_pb2.ExportProductsRequest(), metadata=auth(BUYER_TOKEN))

    with pytest.raises(grpc.aio.AioRpcError) as info:
        _ = [message async for message in call]

    assert info.value.code() is grpc.StatusCode.PERMISSION_DENIED
    status = rich_status(info.value)
    error_info = error_details_pb2.ErrorInfo()
    status.details[0].Unpack(error_info)
    assert error_info.reason == "SELLER_ROLE_REQUIRED"


async def test_seller_on_seller_method(channel: grpc.aio.Channel) -> None:
    call = export(channel)(catalog_pb2.ExportProductsRequest(), metadata=auth(SELLER_TOKEN))

    sellers = {message.product.seller_id async for message in call}

    assert sellers == {"seller-1"}


async def test_health_and_reflection_need_no_api_key(channel: grpc.aio.Channel) -> None:
    check = channel.unary_unary(
        "/grpc.health.v1.Health/Check",
        request_serializer=health_pb2.HealthCheckRequest.SerializeToString,
        response_deserializer=health_pb2.HealthCheckResponse.FromString,
    )

    response = await check(health_pb2.HealthCheckRequest())

    assert response.status == health_pb2.HealthCheckResponse.SERVING


# --- LoggingInterceptor ---


async def test_one_log_line_per_call(channel: grpc.aio.Channel) -> None:
    with capture_logs() as logs:
        await unary(channel)(
            catalog_pb2.GetProductRequest(product_id="p1"),
            metadata=[*auth(), ("x-request-id", "rid-log")],
        )

    calls = [log for log in logs if log["event"] == "grpc.call"]
    assert len(calls) == 1
    assert calls[0]["method"] == f"{CATALOG}/GetProduct"
    assert calls[0]["grpc_type"] == "unary_unary"
    assert calls[0]["request_id"] == "rid-log"
    assert calls[0]["status"] == "OK"
    assert calls[0]["duration_ms"] >= 0
    assert "messages_sent" not in calls[0]


async def test_log_line_has_error_status_and_stream_counts(channel: grpc.aio.Channel) -> None:
    with capture_logs() as logs:
        call = chat_call(channel)(iter(chat_messages("a", "fail")), metadata=auth())
        with pytest.raises(grpc.aio.AioRpcError):
            _ = [response async for response in call]

    [line] = [log for log in logs if log["event"] == "grpc.call"]
    assert line["status"] == "NOT_FOUND"
    assert line["log_level"] == "warning"
    assert line["messages_received"] == 2
    assert line["messages_sent"] == 1


async def test_auth_failure_is_logged(channel: grpc.aio.Channel) -> None:
    with capture_logs() as logs:
        await get_error(
            unary(channel)(
                catalog_pb2.GetProductRequest(product_id="p1"), metadata=auth(api_key=None)
            )
        )

    [line] = [log for log in logs if log["event"] == "grpc.call"]
    assert line["status"] == "UNAUTHENTICATED"


async def test_health_checks_are_not_logged(channel: grpc.aio.Channel) -> None:
    check = channel.unary_unary(
        "/grpc.health.v1.Health/Check",
        request_serializer=health_pb2.HealthCheckRequest.SerializeToString,
        response_deserializer=health_pb2.HealthCheckResponse.FromString,
    )

    with capture_logs() as logs:
        await check(health_pb2.HealthCheckRequest())

    assert [log for log in logs if log["event"] == "grpc.call"] == []
