"""Корневой роутер gateway: собирает группы эндпоинтов из `gateway/routers/`."""

from nuke_di.fastapi import ClientRouter

from gateway.routers import ROUTERS

router = ClientRouter()
for group in ROUTERS:
    router.include_router(group)
