"""Healthcheck для compose через стандартный grpc.health.v1.Health.

    python -m stand_core.grpc.healthcheck [--addr HOST:PORT] [--service catalog.v1.CatalogService]

Код возврата 0 — `SERVING`, иначе 1. Адрес по умолчанию — `localhost:$GRPC_PORT`.
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence

import grpc
from grpc_health.v1 import health_pb2

DEFAULT_TIMEOUT_SECONDS = 2.0


async def check(addr: str, service: str = "", deadline: float = DEFAULT_TIMEOUT_SECONDS) -> bool:
    """`True`, если `service` (пусто — сервер целиком) отвечает `SERVING`."""
    async with grpc.aio.insecure_channel(addr) as channel:
        # Не HealthStub: в его стабах нет методов, а type: ignore вне pb/ не используем
        health_check = channel.unary_unary(
            "/grpc.health.v1.Health/Check",
            request_serializer=health_pb2.HealthCheckRequest.SerializeToString,
            response_deserializer=health_pb2.HealthCheckResponse.FromString,
        )
        try:
            response = await health_check(
                health_pb2.HealthCheckRequest(service=service), timeout=deadline
            )
        except grpc.aio.AioRpcError:
            return False
    return bool(response.status == health_pb2.HealthCheckResponse.SERVING)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m stand_core.grpc.healthcheck")
    parser.add_argument("--addr", default=f"localhost:{os.environ.get('GRPC_PORT', '50051')}")
    parser.add_argument("--service", default="")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    healthy = asyncio.run(check(args.addr, args.service, args.timeout))
    if not healthy:
        print(f"{args.addr} {args.service or '<server>'}: not serving", file=sys.stderr)
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
