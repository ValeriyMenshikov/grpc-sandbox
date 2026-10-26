import asyncio
import socket
from collections.abc import AsyncIterator
from typing import Any

import grpc
import pytest
from catalog.v1 import catalog_pb2
from grpc_health.v1 import health_pb2
from grpc_reflection.v1alpha import reflection_pb2
from stand_core import Context
from stand_core.grpc.healthcheck import check, main
from stand_core.grpc.rpc import MethodAnnotation, MethodSignature, annotate
from stand_core.grpc.server import ProtoMismatchError, RunningServer, grpc_server
from structlog.testing import capture_logs
from support.v1 import support_pb2

from .grpc_handlers import all_call_types, export_products, get_product

CATALOG = "/catalog.v1.CatalogService"


@pytest.fixture
async def running() -> AsyncIterator[RunningServer]:
    async with grpc_server(all_call_types(), port=0, host="localhost", grace=1) as server:
        yield server


@pytest.fixture
async def channel(running: RunningServer) -> AsyncIterator[grpc.aio.Channel]:
    async with grpc.aio.insecure_channel(f"localhost:{running.port}") as channel:
        yield channel


def _unary(channel: grpc.aio.Channel) -> Any:
    return channel.unary_unary(
        f"{CATALOG}/GetProduct",
        request_serializer=catalog_pb2.GetProductRequest.SerializeToString,
        response_deserializer=catalog_pb2.GetProductResponse.FromString,
    )


async def test_unary(channel: grpc.aio.Channel) -> None:
    response = await _unary(channel)(catalog_pb2.GetProductRequest(product_id="p1"))

    assert response.product.product_id == "p1"


async def test_client_stream(channel: grpc.aio.Channel) -> None:
    call = channel.stream_unary(
        f"{CATALOG}/ImportProducts",
        request_serializer=catalog_pb2.ImportProductsRequest.SerializeToString,
        response_deserializer=catalog_pb2.ImportProductsResponse.FromString,
    )

    async def feed() -> AsyncIterator[catalog_pb2.ImportProductsRequest]:
        yield catalog_pb2.ImportProductsRequest(header=catalog_pb2.ImportHeader())
        for offer_id in ("a", "b"):
            yield catalog_pb2.ImportProductsRequest(row=catalog_pb2.ImportRow(offer_id=offer_id))

    response = await call(feed())

    assert response.created == 2


async def test_server_stream(channel: grpc.aio.Channel) -> None:
    call = channel.unary_stream(
        f"{CATALOG}/ExportProducts",
        request_serializer=catalog_pb2.ExportProductsRequest.SerializeToString,
        response_deserializer=catalog_pb2.ExportProductsResponse.FromString,
    )

    ids = [m.product.product_id async for m in call(catalog_pb2.ExportProductsRequest())]

    assert ids == ["p0", "p1", "p2"]


async def test_bidi_stream(channel: grpc.aio.Channel) -> None:
    call = channel.stream_stream(
        "/support.v1.SupportService/Chat",
        request_serializer=support_pb2.ChatRequest.SerializeToString,
        response_deserializer=support_pb2.ChatResponse.FromString,
    )()

    acks = []
    for client_id in ("m1", "m2"):
        message = support_pb2.ClientMessage(client_message_id=client_id, text="где заказ?")
        await call.write(support_pb2.ChatRequest(message=message))
        response = await call.read()
        assert isinstance(response, support_pb2.ChatResponse)
        acks.append(response.ack.client_message_id)
    await call.done_writing()

    assert acks == ["m1", "m2"]
    assert await call.code() == grpc.StatusCode.OK


async def test_method_without_handler_is_unimplemented(channel: grpc.aio.Channel) -> None:
    call = channel.unary_unary(
        f"{CATALOG}/SearchProducts",
        request_serializer=catalog_pb2.SearchProductsRequest.SerializeToString,
        response_deserializer=catalog_pb2.SearchProductsResponse.FromString,
    )

    with pytest.raises(grpc.aio.AioRpcError) as error:
        await call(catalog_pb2.SearchProductsRequest())

    assert error.value.code() == grpc.StatusCode.UNIMPLEMENTED


async def test_methods_without_handler_are_logged_at_start() -> None:
    with capture_logs() as logs:
        async with grpc_server(all_call_types(), port=0, host="localhost", grace=0):
            pass

    warnings = {e["service"]: e["methods"] for e in logs if e["log_level"] == "warning"}
    assert warnings == {
        "catalog.v1.CatalogService": ["SearchProducts"],
        "support.v1.SupportService": ["GetChatHistory", "GetOrderTimeline"],
    }


async def test_health_serving_per_service(
    running: RunningServer, channel: grpc.aio.Channel
) -> None:
    health_check = channel.unary_unary(
        "/grpc.health.v1.Health/Check",
        request_serializer=health_pb2.HealthCheckRequest.SerializeToString,
        response_deserializer=health_pb2.HealthCheckResponse.FromString,
    )

    for service in ("", *running.services):
        response = await health_check(health_pb2.HealthCheckRequest(service=service))
        assert response.status == health_pb2.HealthCheckResponse.SERVING
    assert set(running.services) == {"catalog.v1.CatalogService", "support.v1.SupportService"}


async def test_reflection_lists_registered_services(channel: grpc.aio.Channel) -> None:
    call = channel.stream_stream(
        "/grpc.reflection.v1alpha.ServerReflection/ServerReflectionInfo",
        request_serializer=reflection_pb2.ServerReflectionRequest.SerializeToString,
        response_deserializer=reflection_pb2.ServerReflectionResponse.FromString,
    )()

    await call.write(reflection_pb2.ServerReflectionRequest(list_services=""))
    listed = await call.read()
    await call.write(
        reflection_pb2.ServerReflectionRequest(file_containing_symbol="catalog.v1.CatalogService")
    )
    file = await call.read()
    await call.done_writing()
    assert isinstance(listed, reflection_pb2.ServerReflectionResponse)
    assert isinstance(file, reflection_pb2.ServerReflectionResponse)

    names = {service.name for service in listed.list_services_response.service}
    assert names == {
        "catalog.v1.CatalogService",
        "support.v1.SupportService",
        "grpc.health.v1.Health",
        "grpc.reflection.v1alpha.ServerReflection",
    }
    assert file.file_descriptor_response.file_descriptor_proto


async def test_graceful_stop_finishes_in_flight_call() -> None:
    async with grpc_server(all_call_types(), port=0, host="localhost", grace=2) as server:
        channel = grpc.aio.insecure_channel(f"localhost:{server.port}")
        in_flight = asyncio.ensure_future(
            _unary(channel)(catalog_pb2.GetProductRequest(product_id="slow"))
        )
        await asyncio.sleep(0.1)

    response = await in_flight
    assert response.product.product_id == "slow"
    with pytest.raises(grpc.aio.AioRpcError) as error:
        await _unary(channel)(catalog_pb2.GetProductRequest(product_id="p1"), timeout=1)
    assert error.value.code() == grpc.StatusCode.UNAVAILABLE
    await channel.close()


async def test_port_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    with socket.socket() as sock:
        sock.bind(("localhost", 0))
        port = sock.getsockname()[1]
    monkeypatch.setenv("GRPC_PORT", str(port))

    async with grpc_server(all_call_types(), host="localhost", grace=0) as server:
        assert server.port == port
        assert await check(f"localhost:{port}")


async def _wrong_messages(
    request: catalog_pb2.ExportProductsRequest, context: Context
) -> catalog_pb2.ExportProductsResponse:
    return catalog_pb2.ExportProductsResponse()


def _registry(name: str, handler: Any, service: str = "CatalogService") -> Any:
    return {MethodSignature(name, service, "catalog.v1"): annotate(handler)}


@pytest.mark.parametrize(
    ("handlers", "message"),
    [
        (_registry("GetProduct", export_products), "handler is unary_stream, proto has"),
        (_registry("ExportProducts", get_product), "handler is unary_unary, proto has"),
        (
            _registry("GetProduct", _wrong_messages),
            "request is catalog.v1.ExportProductsRequest, proto has catalog.v1.GetProductRequest",
        ),
        (
            _registry("GetProduct", _wrong_messages),
            "response is catalog.v1.ExportProductsResponse, proto has catalog.v1.GetProductResp",
        ),
        (_registry("DeleteProduct", get_product), "DeleteProduct: method is not in proto"),
        (_registry("GetProduct", get_product, "NoSuchService"), "service catalog.v1.NoSuch"),
    ],
)
async def test_mismatch_with_proto_fails_before_start(
    handlers: dict[MethodSignature, MethodAnnotation], message: str
) -> None:
    with pytest.raises(ProtoMismatchError, match=message):
        async with grpc_server(handlers, port=0, host="localhost"):
            pytest.fail("server must not start")


async def test_healthcheck(running: RunningServer) -> None:
    addr = f"localhost:{running.port}"

    assert await check(addr)
    assert await check(addr, "catalog.v1.CatalogService")
    assert not await check(addr, "orders.v1.OrderService")
    assert await asyncio.to_thread(main, ["--addr", addr]) == 0
    assert await asyncio.to_thread(main, ["--addr", addr, "--service", "nope"]) == 1


async def test_healthcheck_without_server() -> None:
    with socket.socket() as sock:
        sock.bind(("localhost", 0))
        port = sock.getsockname()[1]

    assert not await check(f"localhost:{port}", deadline=0.5)
