"""Общая библиотека стенда: настройки, клиенты, декоратор rpc и gRPC-сервер."""

from stand_core.grpc.context import Context
from stand_core.grpc.rpc import rpc
from stand_core.settings import Settings

__version__ = "0.1.0"

__all__ = ("Context", "Settings", "__version__", "rpc")
