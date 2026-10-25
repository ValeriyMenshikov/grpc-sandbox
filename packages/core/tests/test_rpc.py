from collections.abc import AsyncIterator
from typing import Any

import pytest
from catalog.v1 import catalog_pb2
from stand_core import Context, rpc
from stand_core.grpc.rpc import GRPC_HANDLERS, GrpcTypeEnum, MethodSignature
from support.v1 import support_pb2

GET_PRODUCT = MethodSignature("GetProduct", "CatalogService", "catalog.v1")


def test_unary_handler_is_registered_and_returned_unchanged() -> None:
    async def get_product(
        request: catalog_pb2.GetProductRequest, context: Context
    ) -> catalog_pb2.GetProductResponse:
        return catalog_pb2.GetProductResponse()

    decorated = rpc("GetProduct", package="catalog.v1", service="CatalogService")(get_product)

    assert decorated is get_product
    annotation = GRPC_HANDLERS[GET_PRODUCT]
    assert annotation.method is get_product
    assert annotation.grpc_type is GrpcTypeEnum.unary_unary
    assert annotation.request is catalog_pb2.GetProductRequest
    assert annotation.response is catalog_pb2.GetProductResponse


def test_call_type_comes_from_async_iterator_hints() -> None:
    @rpc("ImportProducts", package="catalog.v1", service="CatalogService")
    async def import_products(
        request: AsyncIterator[catalog_pb2.ImportProductsRequest], context: Context
    ) -> catalog_pb2.ImportProductsResponse:
        return catalog_pb2.ImportProductsResponse()

    @rpc("ExportProducts", package="catalog.v1", service="CatalogService")
    async def export_products(
        request: catalog_pb2.ExportProductsRequest, context: Context
    ) -> AsyncIterator[catalog_pb2.ExportProductsResponse]:
        yield catalog_pb2.ExportProductsResponse()

    @rpc("Chat", package="support.v1", service="SupportService")
    async def chat(
        request: AsyncIterator[support_pb2.ChatRequest], context: Context
    ) -> AsyncIterator[support_pb2.ChatResponse]:
        async for _ in request:
            yield support_pb2.ChatResponse()

    types = {signature.name: a.grpc_type for signature, a in GRPC_HANDLERS.items()}
    assert types == {
        "ImportProducts": GrpcTypeEnum.stream_unary,
        "ExportProducts": GrpcTypeEnum.unary_stream,
        "Chat": GrpcTypeEnum.stream_stream,
    }
    chat_annotation = GRPC_HANDLERS[MethodSignature("Chat", "SupportService", "support.v1")]
    assert chat_annotation.request is support_pb2.ChatRequest
    assert chat_annotation.response is support_pb2.ChatResponse


def test_extra_arguments_after_context_are_allowed() -> None:
    @rpc("GetProduct", package="catalog.v1", service="CatalogService")
    async def get_product(
        request: catalog_pb2.GetProductRequest, context: Context, settings: Any
    ) -> catalog_pb2.GetProductResponse:
        return catalog_pb2.GetProductResponse()

    assert GET_PRODUCT in GRPC_HANDLERS


async def _wrong_order(
    context: Context, request: catalog_pb2.GetProductRequest
) -> catalog_pb2.GetProductResponse:
    return catalog_pb2.GetProductResponse()


async def _no_context(request: catalog_pb2.GetProductRequest) -> catalog_pb2.GetProductResponse:
    return catalog_pb2.GetProductResponse()


async def _request_without_hint(request, context: Context) -> catalog_pb2.GetProductResponse:  # type: ignore[no-untyped-def]
    return catalog_pb2.GetProductResponse()


async def _context_without_hint(request: catalog_pb2.GetProductRequest, context):  # type: ignore[no-untyped-def]
    return catalog_pb2.GetProductResponse()


async def _no_return_annotation(request: catalog_pb2.GetProductRequest, context: Context):  # type: ignore[no-untyped-def]
    return catalog_pb2.GetProductResponse()


async def _not_a_message(request: str, context: Context) -> catalog_pb2.GetProductResponse:
    return catalog_pb2.GetProductResponse()


def _sync_handler(
    request: catalog_pb2.GetProductRequest, context: Context
) -> catalog_pb2.GetProductResponse:
    return catalog_pb2.GetProductResponse()


async def _stream_not_generator(
    request: catalog_pb2.ExportProductsRequest, context: Context
) -> AsyncIterator[catalog_pb2.ExportProductsResponse]:
    raise NotImplementedError


async def _keyword_only(
    *, request: catalog_pb2.GetProductRequest, context: Context
) -> catalog_pb2.GetProductResponse:
    return catalog_pb2.GetProductResponse()


@pytest.mark.parametrize(
    ("handler", "message"),
    [
        (_wrong_order, '"request" and "context"'),
        (_no_context, '"request" and "context"'),
        (_keyword_only, "must be positional"),
        (_request_without_hint, '"request" .* no type hint'),
        (_context_without_hint, '"context" .* no type hint'),
        (_no_return_annotation, "no return annotation"),
        (_not_a_message, "protobuf message"),
        (_sync_handler, "async def"),
        (_stream_not_generator, "async generator"),
    ],
)
def test_invalid_signature_fails_on_decoration(handler: Any, message: str) -> None:
    decorator = rpc("GetProduct", package="catalog.v1", service="CatalogService")

    with pytest.raises(ValueError, match=message):
        decorator(handler)
    assert GRPC_HANDLERS == {}


def test_second_handler_for_same_method_fails() -> None:
    async def first(
        request: catalog_pb2.GetProductRequest, context: Context
    ) -> catalog_pb2.GetProductResponse:
        return catalog_pb2.GetProductResponse()

    async def second(
        request: catalog_pb2.GetProductRequest, context: Context
    ) -> catalog_pb2.GetProductResponse:
        return catalog_pb2.GetProductResponse()

    decorator = rpc("GetProduct", package="catalog.v1", service="CatalogService")
    decorator(first)
    decorator(first)  # повторное декорирование той же функции — не ошибка

    with pytest.raises(ValueError, match="already handled"):
        decorator(second)
    assert GRPC_HANDLERS[GET_PRODUCT].method is first


async def test_decorated_handler_can_be_called_directly() -> None:
    @rpc("GetProduct", package="catalog.v1", service="CatalogService")
    async def get_product(
        request: catalog_pb2.GetProductRequest, context: Context
    ) -> catalog_pb2.GetProductResponse:
        return catalog_pb2.GetProductResponse(
            product=catalog_pb2.Product(product_id=request.product_id)
        )

    response = await get_product(catalog_pb2.GetProductRequest(product_id="p1"), None)  # type: ignore[arg-type]

    assert response.product.product_id == "p1"
