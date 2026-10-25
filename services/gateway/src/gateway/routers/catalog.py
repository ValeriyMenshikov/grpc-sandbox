"""Поиск и карточка товара: эндпоинты поверх catalog-service."""

from typing import Annotated

from catalog.v1 import catalog_pb2
from common.v1 import money_pb2
from fastapi import Query
from nuke_di.fastapi import ClientRouter

from gateway import schemas
from gateway.clients import CatalogClient
from gateway.params import INT64_MAX, PageSize, PageToken

router = ClientRouter(tags=["catalog"])


@router.get("/products")
async def search_products(
    catalog: CatalogClient,
    query: str = "",
    category: str | None = None,
    min_price_kopecks: Annotated[int | None, Query(ge=0, le=INT64_MAX)] = None,
    max_price_kopecks: Annotated[int | None, Query(ge=0, le=INT64_MAX)] = None,
    sort: schemas.ProductSort = "name",
    page_size: PageSize = 0,
    page_token: PageToken = "",
) -> schemas.ProductsPage:
    request = catalog_pb2.SearchProductsRequest(
        query=query,
        sort=schemas.SORT_ORDER[sort],
        pagination=money_pb2.Pagination(page_size=page_size, page_token=page_token),
    )
    if category is not None:
        request.category = category
    if min_price_kopecks is not None:
        request.min_price_kopecks = min_price_kopecks
    if max_price_kopecks is not None:
        request.max_price_kopecks = max_price_kopecks
    return schemas.products_page(await catalog.search_products(request))


@router.get("/products/{product_id}")
async def get_product(product_id: str, catalog: CatalogClient) -> schemas.Product:
    response = await catalog.get_product(product_id)
    return schemas.product(response.product)
