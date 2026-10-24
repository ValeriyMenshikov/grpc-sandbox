from catalog.v1 import catalog_pb2
from stand_core import Context, rpc
from stand_core.grpc import InvalidArgument

from catalog_service.convert import product_v1
from catalog_service.models import ProductFilter, ProductSort
from catalog_service.repository import CatalogRepository
from catalog_service.search import price_range_violations, search_page

SORTS: dict[int, ProductSort] = {
    catalog_pb2.SORT_ORDER_UNSPECIFIED: ProductSort.NAME,
    catalog_pb2.SORT_ORDER_PRICE_ASC: ProductSort.PRICE_ASC,
    catalog_pb2.SORT_ORDER_PRICE_DESC: ProductSort.PRICE_DESC,
    catalog_pb2.SORT_ORDER_NEWEST: ProductSort.NEWEST,
}


@rpc("SearchProducts", package="catalog.v1", service="CatalogService")
async def search_products(
    request: catalog_pb2.SearchProductsRequest,
    context: Context,
    repository: CatalogRepository,
) -> catalog_pb2.SearchProductsResponse:
    min_price = request.min_price_kopecks if request.HasField("min_price_kopecks") else None
    max_price = request.max_price_kopecks if request.HasField("max_price_kopecks") else None
    violations = price_range_violations(
        min_price, max_price, "min_price_kopecks", "max_price_kopecks"
    )
    if violations:
        raise InvalidArgument(violations)
    page = await search_page(
        repository,
        ProductFilter(
            query=request.query.strip(),
            category=request.category if request.HasField("category") else None,
            min_price_kopecks=min_price,
            max_price_kopecks=max_price,
            # Неизвестное значение enum (клиент новее сервера) — сортировка по умолчанию
            sort=SORTS.get(request.sort, ProductSort.NAME),
        ),
        request.pagination,
    )
    return catalog_pb2.SearchProductsResponse(
        products=[product_v1(product) for product in page.products],
        next_page_token=page.next_page_token,
    )
