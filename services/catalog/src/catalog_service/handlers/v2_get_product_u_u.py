from catalog.v2 import catalog_pb2
from stand_core import Context, rpc

from catalog_service.convert import product_v2
from catalog_service.handlers.get_product_u_u import find_product
from catalog_service.repository import CatalogRepository


@rpc("GetProduct", package="catalog.v2", service="CatalogService")
async def get_product_v2(
    request: catalog_pb2.GetProductRequest,
    context: Context,
    repository: CatalogRepository,
) -> catalog_pb2.GetProductResponse:
    product = await find_product(repository, request.product_id)
    return catalog_pb2.GetProductResponse(product=product_v2(product))
