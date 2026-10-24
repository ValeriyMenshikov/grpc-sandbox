from catalog.v2 import catalog_pb2
from stand_core import Context, rpc
from stand_core.grpc import FieldViolation, InvalidArgument

from catalog_service.convert import money_to_kopecks, product_v2
from catalog_service.models import ProductFilter, ProductSort
from catalog_service.repository import CatalogRepository
from catalog_service.search import price_range_violations, search_page

SORTS: dict[int, ProductSort] = {
    catalog_pb2.SORT_ORDER_UNSPECIFIED: ProductSort.NAME,
    catalog_pb2.SORT_ORDER_PRICE_ASC: ProductSort.PRICE_ASC,
    catalog_pb2.SORT_ORDER_PRICE_DESC: ProductSort.PRICE_DESC,
    catalog_pb2.SORT_ORDER_NEWEST: ProductSort.NEWEST,
}


@rpc("SearchProducts", package="catalog.v2", service="CatalogService")
async def search_products_v2(
    request: catalog_pb2.SearchProductsRequest,
    context: Context,
    repository: CatalogRepository,
) -> catalog_pb2.SearchProductsResponse:
    violations: list[FieldViolation] = []
    # Регион обязателен по контракту v2, но на выдачу пока не влияет (docs/decisions.md)
    if not request.region_id.strip():
        violations.append(FieldViolation("region_id", "is required"))
    min_price = max_price = None
    if request.HasField("min_price"):
        min_price, money_violations = money_to_kopecks(request.min_price, "min_price")
        violations += money_violations
    if request.HasField("max_price"):
        max_price, money_violations = money_to_kopecks(request.max_price, "max_price")
        violations += money_violations
    violations += price_range_violations(min_price, max_price, "min_price", "max_price")
    if violations:
        raise InvalidArgument(violations)

    page = await search_page(
        repository,
        ProductFilter(
            query=request.query.strip(),
            category=request.category if request.HasField("category") else None,
            min_price_kopecks=min_price,
            max_price_kopecks=max_price,
            sort=SORTS.get(request.sort, ProductSort.NAME),
        ),
        request.pagination,
    )
    return catalog_pb2.SearchProductsResponse(
        products=[product_v2(product) for product in page.products],
        next_page_token=page.next_page_token,
    )
