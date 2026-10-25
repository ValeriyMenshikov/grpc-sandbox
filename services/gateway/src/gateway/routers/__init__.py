"""Роутеры gateway: по одному модулю на группу эндпоинтов. Собирает их `gateway/api.py`."""

from gateway.routers import cart, catalog, health, orders, users

# Порядок = порядок групп в OpenAPI
ROUTERS = (health.router, users.router, catalog.router, cart.router, orders.router)

__all__ = ["ROUTERS", "cart", "catalog", "health", "orders", "users"]
