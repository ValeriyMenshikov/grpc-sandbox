"""Хэндлеры catalog-service: импорт пакета регистрирует их в `GRPC_HANDLERS`."""

from catalog_service.handlers import (
    export_products_u_s,
    get_product_u_u,
    import_products_s_u,
    search_products_u_u,
    v2_get_product_u_u,
    v2_search_products_u_u,
)

__all__ = (
    "export_products_u_s",
    "get_product_u_u",
    "import_products_s_u",
    "search_products_u_u",
    "v2_get_product_u_u",
    "v2_search_products_u_u",
)
