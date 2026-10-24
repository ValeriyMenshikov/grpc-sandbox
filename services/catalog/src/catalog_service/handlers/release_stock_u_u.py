from catalog.v1 import catalog_pb2
from stand_core import Context, rpc
from stand_core.grpc import FieldViolation, InvalidArgument

from catalog_service.repository import CatalogRepository


@rpc("ReleaseStock", package="catalog.v1", service="StockService")
async def release_stock(
    request: catalog_pb2.ReleaseStockRequest,
    context: Context,
    repository: CatalogRepository,
) -> catalog_pb2.ReleaseStockResponse:
    if not request.order_id:
        raise InvalidArgument([FieldViolation("order_id", "must not be empty")])
    released = await repository.release_stock(request.order_id)
    return catalog_pb2.ReleaseStockResponse(order_id=request.order_id, released=released)
