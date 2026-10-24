"""Связка реестра `rpc` с nuke-di: внедрение клиентов в хэндлеры и резолв интерцепторов.

`@worker` запускает процесс в момент декорирования, если модуль — `__main__`, поэтому хэндлеры и
интерцепторы внедряются на уровне модуля, до worker'а, а worker — последний в файле. Образец —
`services/catalog/src/catalog_service/main.py` (его копия — шаблон `main.py` в CLAUDE.md).
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from functools import partial

import grpc
from nuke_di import DI, Client, Dependencies

from stand_core.grpc.interceptors import DEFAULT_INTERCEPTORS
from stand_core.grpc.rpc import MethodAnnotation, MethodSignature


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
    """Резолв интерцепторов через контейнер; каждый — и `ServerInterceptor`, и nuke-di `Client`.

    По умолчанию — `DEFAULT_INTERCEPTORS` в порядке ТЗ 5.4 (RequestId, Logging, Auth, StreamCount,
    ExceptionHandling); `AuthInterceptor` тянет за собой `Sessions` → `Redis`.
    """
    resolved: list[grpc.aio.ServerInterceptor] = []
    for interceptor_class in DEFAULT_INTERCEPTORS if interceptors is None else interceptors:
        interceptor = container.resolve(interceptor_class)
        if not isinstance(interceptor, grpc.aio.ServerInterceptor):
            raise TypeError(f"{interceptor_class.__qualname__} is not a grpc.aio.ServerInterceptor")
        resolved.append(interceptor)
    return resolved
