from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import UTC

from catalog.v1 import catalog_pb2
from stand_core import Context, rpc
from stand_core.grpc import current_user

from catalog_service.convert import product_v1
from catalog_service.repository import CatalogRepository


@rpc("ExportProducts", package="catalog.v1", service="CatalogService")
async def export_products(
    request: catalog_pb2.ExportProductsRequest,
    context: Context,
    repository: CatalogRepository,
) -> AsyncIterator[catalog_pb2.ExportProductsResponse]:
    """Товары текущего продавца по одному; x-items-count выставляет StreamCountInterceptor."""
    seller = current_user()
    updated_since = (
        request.updated_since.ToDatetime(tzinfo=UTC) if request.HasField("updated_since") else None
    )
    # aclosing: клиент ушёл посреди выгрузки — курсор и соединение с Postgres освобождаются сразу
    async with aclosing(repository.export_products(seller.id, updated_since)) as products:
        async for product in products:
            if context.done():
                return
            yield catalog_pb2.ExportProductsResponse(product=product_v1(product))
