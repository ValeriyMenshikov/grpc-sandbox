"""Политики авторизации методов catalog-service (ТЗ 6.0, 6.2, 6.3)."""

from stand_core.grpc import AuthPolicy

V1_CATALOG = "/catalog.v1.CatalogService"
V1_STOCK = "/catalog.v1.StockService"
V2_CATALOG = "/catalog.v2.CatalogService"

AUTH_POLICIES: dict[str, AuthPolicy] = {
    f"{V1_CATALOG}/GetProduct": AuthPolicy.SERVICE,
    f"{V1_CATALOG}/SearchProducts": AuthPolicy.SERVICE,
    f"{V1_CATALOG}/ImportProducts": AuthPolicy.SELLER,
    f"{V1_CATALOG}/ExportProducts": AuthPolicy.SELLER,
    f"{V1_STOCK}/GetStock": AuthPolicy.SERVICE,
    f"{V1_STOCK}/ReserveStock": AuthPolicy.SERVICE,
    f"{V1_STOCK}/ReleaseStock": AuthPolicy.SERVICE,
    f"{V2_CATALOG}/GetProduct": AuthPolicy.SERVICE,
    f"{V2_CATALOG}/SearchProducts": AuthPolicy.SERVICE,
}
