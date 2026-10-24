from catalog.v1 import catalog_pb2
from stand_core import Context, rpc
from stand_core.grpc import FieldViolation, InvalidArgument, NotFound

from catalog_service.convert import product_v1
from catalog_service.models import Product
from catalog_service.repository import CatalogRepository


async def find_product(repository: CatalogRepository, product_id: str) -> Product:
    """Товар по id, общий для v1 и v2: пустой id — INVALID_ARGUMENT, нет товара — NOT_FOUND."""
    if not product_id:
        raise InvalidArgument([FieldViolation("product_id", "must not be empty")])
    product = await repository.get_product(product_id)
    if product is None:
        raise NotFound("product", product_id)
    return product


@rpc("GetProduct", package="catalog.v1", service="CatalogService")
async def get_product(
    request: catalog_pb2.GetProductRequest,
    context: Context,
    repository: CatalogRepository,
) -> catalog_pb2.GetProductResponse:
    product = await find_product(repository, request.product_id)
    return catalog_pb2.GetProductResponse(product=product_v1(product))
