"""Связка реестра `rpc` с nuke-di: внедрение клиентов в хэндлеры и резолв интерцепторов.

`@worker` запускает процесс в момент декорирования, если модуль — `__main__`, поэтому хэндлеры и
интерцепторы внедряются на уровне модуля, до worker'а, а worker — последний в файле::

    # services/catalog/src/catalog_service/main.py
    from nuke_di import Shutdown, worker
    from stand_core.grpc import GRPC_HANDLERS, grpc_server, inject_handlers, resolve_interceptors

    import catalog_service.handlers  # noqa: F401  — регистрирует хэндлеры

    HANDLERS = inject_handlers(GRPC_HANDLERS)  # DI.inject каждого хэндлера, до connect()
    INTERCEPTORS = resolve_interceptors()  # DI.resolve каждого интерцептора (они — Client)


    @worker
    async def serve(shutdown: Shutdown) -> None:
        async with grpc_server(HANDLERS, INTERCEPTORS):
            await shutdown.wait()
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from functools import partial

import grpc
from nuke_di import DI, Client, Dependencies

from stand_core.grpc.rpc import MethodAnnotation, MethodSignature

# Интерцепторы стенда по умолчанию, в порядке выполнения. Заполняется вместе с интерцепторами.
DEFAULT_INTERCEPTORS: tuple[type[Client], ...] = ()


def inject_handlers(
    grpc_handlers: Mapping[MethodSignature, MethodAnnotation],
    container: Dependencies = DI,
) -> dict[MethodSignature, MethodAnnotation]:
    """Копия реестра, в которой у каждого хэндлера связаны клиенты из его сигнатуры.

    Уже внедрённые (`functools.partial`) хэндлеры пропускаются, как в Nuke. Вызывать до `connect()`.
    """
    return {
        signature: (
            annotation
            if isinstance(annotation.method, partial)
            else replace(annotation, method=container.inject(annotation.method))
        )
        for signature, annotation in grpc_handlers.items()
    }


def resolve_interceptors(
    interceptors: Sequence[type[Client]] | None = None,
    container: Dependencies = DI,
) -> list[grpc.aio.ServerInterceptor]:
    """Резолв интерцепторов через контейнер; каждый — и `ServerInterceptor`, и nuke-di `Client`."""
    resolved: list[grpc.aio.ServerInterceptor] = []
    for interceptor_class in DEFAULT_INTERCEPTORS if interceptors is None else interceptors:
        interceptor = container.resolve(interceptor_class)
        if not isinstance(interceptor, grpc.aio.ServerInterceptor):
            raise TypeError(f"{interceptor_class.__qualname__} is not a grpc.aio.ServerInterceptor")
        resolved.append(interceptor)
    return resolved
