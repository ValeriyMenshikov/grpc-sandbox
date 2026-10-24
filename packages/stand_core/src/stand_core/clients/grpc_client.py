"""Базовый gRPC-клиент к соседнему сервису как nuke-di Client (ТЗ 5.5)."""

import os
from collections.abc import Sequence
from typing import ClassVar, TypeVar

import grpc
from google.protobuf.message import Message
from nuke_di import Client

from stand_core.grpc.context import authorization, request_id, time_remaining
from stand_core.grpc.errors import DependencyUnavailable
from stand_core.settings import Settings

ResponseT = TypeVar("ResponseT", bound=Message)

# Статусы соседа, которые значат «сосед недоступен», а не ответ по существу
UNAVAILABLE_CODES = frozenset({grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED})


class GrpcClient(Client):
    """Канал grpc.aio к соседу + вызов с пробросом контекста входящего вызова.

    Подкласс задаёт `address_env` (например, `CATALOG_ADDR` — так курс подменяет соседа моком) и
    `dependency` (имя соседа для `DependencyUnavailable`) и объявляет типизированные методы
    поверх `unary()`::

        class StockClient(GrpcClient):
            address_env = "CATALOG_ADDR"
            dependency = "catalog"

            async def reserve(self, request: ReserveStockRequest) -> ReserveStockResponse:
                return await self.unary(
                    "/catalog.v1.StockService/ReserveStock", request, ReserveStockResponse
                )

    Каждый вызов несёт `x-api-key` сервиса и `x-request-id` текущего вызова; deadline — остаток
    deadline входящего вызова, без него — `GRPC_DEFAULT_DEADLINE_SECONDS`. `UNAVAILABLE` и
    `DEADLINE_EXCEEDED` соседа превращаются в `DependencyUnavailable`, прочие ошибки остаются
    `grpc.aio.AioRpcError` — их разбирает сервис.
    """

    address_env: ClassVar[str]
    dependency: ClassVar[str]

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._channel: grpc.aio.Channel | None = None

    @property
    def channel(self) -> grpc.aio.Channel:
        if self._channel is None:
            raise RuntimeError(f"{type(self).__qualname__} is not connected")
        return self._channel

    async def connect(self) -> None:
        # Канал ленивый: сосед может подняться позже, его недоступность — UNAVAILABLE у вызова
        address = os.environ.get(self.address_env)
        if not address:
            raise RuntimeError(f"{self.address_env} is not set")
        self._channel = grpc.aio.insecure_channel(address)

    async def disconnect(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None

    def metadata(
        self, *, forward_authorization: bool = False, extra: Sequence[tuple[str, str]] = ()
    ) -> tuple[tuple[str, str], ...]:
        items = [("x-api-key", self._settings.stand_api_key)]
        current_request_id = request_id()
        if current_request_id is not None:
            items.append(("x-request-id", current_request_id))
        current_authorization = authorization()
        if forward_authorization and current_authorization is not None:
            items.append(("authorization", current_authorization))
        items.extend(extra)
        return tuple(items)

    def timeout(self) -> float:
        remaining = time_remaining()
        return self._settings.grpc_default_deadline_seconds if remaining is None else remaining

    async def unary(
        self,
        method: str,
        request: Message,
        response_type: type[ResponseT],
        *,
        forward_authorization: bool = False,
        metadata: Sequence[tuple[str, str]] = (),
        deadline: float | None = None,
    ) -> ResponseT:
        """Unary-вызов `method` ("/package.Service/Method"); `deadline` — секунды на вызов."""
        multicallable = self.channel.unary_unary(
            method,
            request_serializer=type(request).SerializeToString,
            response_deserializer=response_type.FromString,
        )
        try:
            response: ResponseT = await multicallable(
                request,
                timeout=self.timeout() if deadline is None else deadline,
                metadata=self.metadata(forward_authorization=forward_authorization, extra=metadata),
            )
        except grpc.aio.AioRpcError as exc:
            if exc.code() in UNAVAILABLE_CODES:
                raise DependencyUnavailable(
                    self.dependency, f"{self.dependency} is unavailable: {exc.code().name}"
                ) from exc
            raise
        return response
