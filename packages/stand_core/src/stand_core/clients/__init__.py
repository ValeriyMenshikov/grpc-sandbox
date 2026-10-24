"""nuke-di клиенты стенда: Postgres, Redis."""

from stand_core.clients.postgres import Postgres
from stand_core.clients.redis import Redis

__all__ = ("Postgres", "Redis")
