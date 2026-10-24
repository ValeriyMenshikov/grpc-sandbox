from catalog.v1 import catalog_pb2
from stand_core import Context, rpc
from stand_core.grpc import FieldViolation, InvalidArgument, NotFound

from catalog_service.repository import CatalogRepository


@rpc("GetStock", package="catalog.v1", service="StockService")
async def get_stock(
    request: catalog_pb2.GetStockRequest,
    context: Context,
    repository: CatalogRepository,
) -> catalog_pb2.GetStockResponse:
    if not request.product_id:
        raise InvalidArgument([FieldViolation("product_id", "must not be empty")])
    available = await repository.get_available(request.product_id)
    if available is None:
        raise NotFound("product", request.product_id)
    return catalog_pb2.GetStockResponse(product_id=request.product_id, available=available)
