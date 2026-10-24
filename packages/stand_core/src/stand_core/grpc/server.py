"""gRPC-сервер стенда: generic handlers из реестра `rpc`, сверка с proto, reflection, health.

Как в Nuke, плюс обязательные улучшения из ТЗ (5.2): сверка хэндлеров с дескрипторами до
`server.start()`, health `SERVING` по каждому сервису и graceful stop.
"""

import os
from collections import defaultdict
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import grpc
from google.protobuf import descriptor_pool
from google.protobuf.descriptor import ServiceDescriptor
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection

from stand_core.grpc.rpc import METHOD_MAP, MethodAnnotation, MethodSignature
from stand_core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_GRPC_PORT = 50051
DEFAULT_SHUTDOWN_GRACE_SECONDS = 5.0

# Keepalive-опции из Nuke
SERVER_OPTIONS: tuple[tuple[str, int], ...] = (
    ("grpc.http2.min_ping_interval_without_data_ms", 1000),
    ("grpc.http2.max_ping_strikes", 3),
    ("grpc.keepalive_permit_without_calls", 1),
    ("grpc.keepalive_time_ms", 20000),
)


class ProtoMismatchError(ValueError):
    """Хэндлеры не совпадают с proto-контрактом; сервер не стартует."""


@dataclass(frozen=True)
class RunningServer:
    server: grpc.aio.Server
    port: int
    services: tuple[str, ...]


def validate_handlers(
    grpc_handlers: Mapping[MethodSignature, MethodAnnotation],
    pool: descriptor_pool.DescriptorPool | None = None,
) -> dict[str, ServiceDescriptor]:
    """Сверить хэндлеры с дескрипторами из пула; вернуть дескрипторы сервисов по полному имени.

    Все расхождения собираются в одну `ProtoMismatchError`. Модули `_pb2` сервисов должны быть
    импортированы: дескрипторы берутся из пула по умолчанию.
    """
    pool = pool or descriptor_pool.Default()
    services: dict[str, ServiceDescriptor] = {}
    problems: list[str] = []

    for signature, annotation in grpc_handlers.items():
        full_service = signature.full_service
        if full_service not in services:
            try:
                services[full_service] = pool.FindServiceByName(full_service)
            except KeyError:
                problems.append(f"{signature.full_method}: service {full_service} is not in proto")
                continue
        method = services[full_service].methods_by_name.get(signature.name)
        if method is None:
            problems.append(f"{signature.full_method}: method is not in proto")
            continue

        grpc_type = annotation.grpc_type
        if (method.client_streaming, method.server_streaming) != (
            grpc_type.client_streaming,
            grpc_type.server_streaming,
        ):
            problems.append(
                f"{signature.full_method}: handler is {grpc_type}, proto has "
                f"client_streaming={method.client_streaming}, "
                f"server_streaming={method.server_streaming}"
            )
        if annotation.request.DESCRIPTOR.full_name != method.input_type.full_name:
            problems.append(
                f"{signature.full_method}: request is {annotation.request.DESCRIPTOR.full_name}, "
                f"proto has {method.input_type.full_name}"
            )
        if annotation.response.DESCRIPTOR.full_name != method.output_type.full_name:
            problems.append(
                f"{signature.full_method}: response is {annotation.response.DESCRIPTOR.full_name}, "
                f"proto has {method.output_type.full_name}"
            )

    if problems:
        raise ProtoMismatchError("Handlers do not match proto:\n" + "\n".join(problems))
    return services


def build_generic_handlers(
    grpc_handlers: Mapping[MethodSignature, MethodAnnotation],
) -> list[grpc.GenericRpcHandler]:
    """Один generic handler на сервис `package.service`; неизвестный метод → UNIMPLEMENTED."""
    by_service: dict[str, dict[str, grpc.RpcMethodHandler[Any, Any]]] = defaultdict(dict)
    for signature, annotation in grpc_handlers.items():
        by_service[signature.full_service][signature.name] = METHOD_MAP[annotation.grpc_type](
            annotation.method,
            request_deserializer=annotation.request.FromString,
            response_serializer=annotation.response.SerializeToString,
        )
    return [
        grpc.method_handlers_generic_handler(service, methods)
        for service, methods in by_service.items()
    ]


@asynccontextmanager
async def grpc_server(
    grpc_handlers: Mapping[MethodSignature, MethodAnnotation],
    interceptors: Sequence[grpc.aio.ServerInterceptor] = (),
    *,
    port: int | None = None,
    grace: float | None = None,
    host: str = "[::]",
) -> AsyncIterator[RunningServer]:
    """Запустить gRPC-сервер на время блока.

    `port` по умолчанию — env `GRPC_PORT` (0 — свободный порт, см. `RunningServer.port`).
    `grace` по умолчанию — `SHUTDOWN_GRACE_SECONDS - 1`, чтобы уложиться в общий таймаут остановки.
    """
    services = validate_handlers(grpc_handlers)
    if port is None:
        port = int(os.environ.get("GRPC_PORT", DEFAULT_GRPC_PORT))
    if grace is None:
        shutdown_grace = float(
            os.environ.get("SHUTDOWN_GRACE_SECONDS", DEFAULT_SHUTDOWN_GRACE_SECONDS)
        )
        grace = max(shutdown_grace - 1.0, 0.0)

    for full_service, service in services.items():
        missing = [
            name
            for name in service.methods_by_name
            if MethodSignature(name, service.name, service.file.package) not in grpc_handlers
        ]
        if missing:
            logger.warning("grpc.unimplemented_methods", service=full_service, methods=missing)

    server = grpc.aio.server(interceptors=list(interceptors), options=list(SERVER_OPTIONS))
    try:
        server.add_generic_rpc_handlers(build_generic_handlers(grpc_handlers))

        health_servicer = health.aio.HealthServicer()
        health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
        await health_servicer.set(health.OVERALL_HEALTH, health_pb2.HealthCheckResponse.NOT_SERVING)

        service_names = tuple(services)
        reflection.enable_server_reflection(
            (*service_names, health.SERVICE_NAME, reflection.SERVICE_NAME), server
        )

        bound_port = server.add_insecure_port(f"{host}:{port}")
        await server.start()
        for name in (*service_names, health.OVERALL_HEALTH):
            await health_servicer.set(name, health_pb2.HealthCheckResponse.SERVING)
        logger.info("grpc.server_started", port=bound_port, services=list(service_names))

        yield RunningServer(server=server, port=bound_port, services=service_names)

        logger.info("grpc.server_stopping", grace=grace)
        await health_servicer.enter_graceful_shutdown()
        await server.stop(grace)
    finally:
        await server.stop(None)
