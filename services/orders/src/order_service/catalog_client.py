"""Клиент к CatalogService: название, цена и доступный остаток товара."""

import asyncio
from collections.abc import Iterable

import grpc
from catalog.v1 import catalog_pb2
from stand_core.clients import GrpcClient

GET_PRODUCT = "/catalog.v1.CatalogService/GetProduct"


class CatalogClient(GrpcClient):
    address_env = "CATALOG_ADDR"
    dependency = "catalog"

    async def get_product(self, product_id: str) -> catalog_pb2.Product | None:
        """Товар из catalog; None — товара нет (NOT_FOUND соседа)."""
        try:
            response = await self.unary(
                GET_PRODUCT,
                catalog_pb2.GetProductRequest(product_id=product_id),
                catalog_pb2.GetProductResponse,
            )
        except grpc.aio.AioRpcError as exc:
            if exc.code() is grpc.StatusCode.NOT_FOUND:
                return None
            raise
        return response.product

    async def get_products(self, product_ids: Iterable[str]) -> dict[str, catalog_pb2.Product]:
        """Товары параллельными GetProduct; отсутствующих в результате нет."""
        ids = list(dict.fromkeys(product_ids))
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(self.get_product(product_id)) for product_id in ids]
        return {
            product_id: product
            for product_id, task in zip(ids, tasks, strict=True)
            if (product := task.result()) is not None
        }
