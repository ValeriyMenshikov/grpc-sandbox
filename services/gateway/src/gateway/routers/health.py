"""Healthcheck gateway."""

from nuke_di.fastapi import ClientRouter

from gateway import schemas

router = ClientRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> schemas.Health:
    """Healthcheck контейнера: процесс отвечает, соседей не трогает."""
    return schemas.Health()
