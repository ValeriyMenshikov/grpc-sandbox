"""Тестовые хэндлеры всех четырёх типов вызовов на реальных дескрипторах из gen/."""

import asyncio
from collections.abc import AsyncIterator

from catalog.v1 import catalog_pb2
from stand_core import Context
from stand_core.grpc.rpc import MethodAnnotation, MethodSignature, annotate
from support.v1 import support_pb2


async def get_product(
    request: catalog_pb2.GetProductRequest, context: Context
) -> catalog_pb2.GetProductResponse:
    if request.product_id == "slow":
        await asyncio.sleep(0.3)
    return catalog_pb2.GetProductResponse(
        product=catalog_pb2.Product(product_id=request.product_id, name="Чайник")
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
            product=catalog_pb2.Product(product_id=f"p{index}")
        )


async def chat(
    request: AsyncIterator[support_pb2.ChatRequest], context: Context
) -> AsyncIterator[support_pb2.ChatResponse]:
    async for message in request:
        yield support_pb2.ChatResponse(
            ack=support_pb2.Ack(client_message_id=message.message.client_message_id)
        )


def all_call_types() -> dict[MethodSignature, MethodAnnotation]:
    catalog = ("CatalogService", "catalog.v1")
    return {
        MethodSignature("GetProduct", *catalog): annotate(get_product),
        MethodSignature("ImportProducts", *catalog): annotate(import_products),
        MethodSignature("ExportProducts", *catalog): annotate(export_products),
        MethodSignature("Chat", "SupportService", "support.v1"): annotate(chat),
    }
