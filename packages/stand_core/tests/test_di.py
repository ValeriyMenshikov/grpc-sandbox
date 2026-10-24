# Аннотации строками: в рантайме grpc.RpcMethodHandler не параметризуется
from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

import grpc
import pytest
from catalog.v1 import catalog_pb2
from nuke_di import Client, Dependencies
from stand_core import Context
from stand_core.grpc.di import inject_handlers, resolve_interceptors
from stand_core.grpc.rpc import MethodSignature, annotate
from stand_core.grpc.server import grpc_server

GET_PRODUCT = MethodSignature("GetProduct", "CatalogService", "catalog.v1")


class Names(Client):
    def __init__(self) -> None:
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    def name(self, product_id: str) -> str:
        return f"product {product_id}" if self.connected else "not connected"


class Calls(Client):
    def __init__(self) -> None:
        self.methods: list[str] = []


class CountingInterceptor(grpc.aio.ServerInterceptor, Client):
    def __init__(self, calls: Calls) -> None:
        self.calls = calls

    async def intercept_service(
        self,
        continuation: Callable[
            [grpc.HandlerCallDetails], Awaitable[grpc.RpcMethodHandler[Any, Any] | None]
        ],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler[Any, Any] | None:
        self.calls.methods.append(handler_call_details.method)
        return await continuation(handler_call_details)


async def get_product(
    request: catalog_pb2.GetProductRequest, context: Context, names: Names
) -> catalog_pb2.GetProductResponse:
    return catalog_pb2.GetProductResponse(
        product=catalog_pb2.Product(
            product_id=request.product_id, name=names.name(request.product_id)
        )
    )


@pytest.fixture
def container() -> Dependencies:
    return Dependencies()


def test_inject_handlers_binds_clients(container: Dependencies) -> None:
    handlers = {GET_PRODUCT: annotate(get_product)}

    injected = inject_handlers(handlers, container)

    method = injected[GET_PRODUCT].method
    assert isinstance(method, partial)
    assert method.keywords == {"names": container.resolve(Names)}
    # Исходный реестр не меняется
    assert handlers[GET_PRODUCT].method is get_product


def test_inject_handlers_skips_already_injected(container: Dependencies) -> None:
    injected = inject_handlers({GET_PRODUCT: annotate(get_product)}, container)

    again = inject_handlers(injected, Dependencies())

    assert again[GET_PRODUCT].method is injected[GET_PRODUCT].method


def test_resolve_interceptors_resolves_through_container(container: Dependencies) -> None:
    interceptors = resolve_interceptors([CountingInterceptor], container)

    assert interceptors == [container.resolve(CountingInterceptor)]
    assert container.resolve(CountingInterceptor).calls is container.resolve(Calls)


def test_resolve_interceptors_rejects_non_interceptor(container: Dependencies) -> None:
    with pytest.raises(TypeError, match=r"not a grpc\.aio\.ServerInterceptor"):
        resolve_interceptors([Calls], container)


def test_resolve_interceptors_defaults_to_stand_interceptors(container: Dependencies) -> None:
    assert resolve_interceptors(container=container) == []


async def test_injected_handler_and_interceptor_serve_calls(container: Dependencies) -> None:
    handlers = inject_handlers({GET_PRODUCT: annotate(get_product)}, container)
    interceptors = resolve_interceptors([CountingInterceptor], container)

    async with (
        container,
        grpc_server(handlers, interceptors, port=0, host="localhost", grace=0) as server,
        grpc.aio.insecure_channel(f"localhost:{server.port}") as channel,
    ):
        call = channel.unary_unary(
            "/catalog.v1.CatalogService/GetProduct",
            request_serializer=catalog_pb2.GetProductRequest.SerializeToString,
            response_deserializer=catalog_pb2.GetProductResponse.FromString,
        )
        response = await call(catalog_pb2.GetProductRequest(product_id="p1"))

    assert response.product.name == "product p1"
    (interceptor,) = interceptors
    assert isinstance(interceptor, CountingInterceptor)
    assert interceptor.calls.methods == ["/catalog.v1.CatalogService/GetProduct"]
