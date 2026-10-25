"""Декоратор `rpc` и реестр хэндлеров (как в Nuke).

Хэндлер — свободная async-функция `(request, context, *clients)`. Тип вызова и классы сообщений
берутся из type hints: `AsyncIterator[Req]` у `request` — входящий стрим, `-> AsyncIterator[Resp]` —
исходящий (хэндлер — async-генератор). Декоратор только регистрирует хэндлер в `GRPC_HANDLERS` и
возвращает функцию без изменений.
"""

import inspect
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar, get_args, get_origin, get_type_hints

import grpc
from google.protobuf.message import Message

HandlerT = TypeVar("HandlerT", bound=Callable[..., Any])


class GrpcTypeEnum(StrEnum):
    stream_stream = "stream_stream"
    stream_unary = "stream_unary"
    unary_stream = "unary_stream"
    unary_unary = "unary_unary"

    @property
    def client_streaming(self) -> bool:
        return self in (GrpcTypeEnum.stream_stream, GrpcTypeEnum.stream_unary)

    @property
    def server_streaming(self) -> bool:
        return self in (GrpcTypeEnum.stream_stream, GrpcTypeEnum.unary_stream)


# (входящий стрим, исходящий стрим) → тип вызова
IN_OUT_METHOD_TYPE: dict[tuple[bool, bool], GrpcTypeEnum] = {
    (True, True): GrpcTypeEnum.stream_stream,
    (True, False): GrpcTypeEnum.stream_unary,
    (False, True): GrpcTypeEnum.unary_stream,
    (False, False): GrpcTypeEnum.unary_unary,
}

# Аннотация в кавычках: в рантайме grpc.RpcMethodHandler не параметризуется
METHOD_MAP: "dict[GrpcTypeEnum, Callable[..., grpc.RpcMethodHandler[Any, Any]]]" = {
    GrpcTypeEnum.stream_stream: grpc.stream_stream_rpc_method_handler,
    GrpcTypeEnum.stream_unary: grpc.stream_unary_rpc_method_handler,
    GrpcTypeEnum.unary_stream: grpc.unary_stream_rpc_method_handler,
    GrpcTypeEnum.unary_unary: grpc.unary_unary_rpc_method_handler,
}


@dataclass(frozen=True)
class MethodSignature:
    name: str  # "ImportProducts"
    service: str  # "CatalogService"
    package: str  # "catalog.v1"

    @property
    def full_service(self) -> str:
        return f"{self.package}.{self.service}"

    @property
    def full_method(self) -> str:
        """Полное имя метода, как его видит интерцептор: `/catalog.v1.CatalogService/GetProduct`."""
        return f"/{self.full_service}/{self.name}"


@dataclass
class MethodAnnotation:
    request: type[Message]
    response: type[Message]
    method: Callable[..., Any]
    grpc_type: GrpcTypeEnum


GRPC_HANDLERS: dict[MethodSignature, MethodAnnotation] = {}


def rpc(method_name: str, package: str, service: str) -> Callable[[HandlerT], HandlerT]:
    """Зарегистрировать хэндлер метода `package.service/method_name` в `GRPC_HANDLERS`.

    Неверная сигнатура или повторная регистрация метода — `ValueError` при импорте модуля.
    """
    signature = MethodSignature(name=method_name, service=service, package=package)

    def decorator(func: HandlerT) -> HandlerT:
        annotation = annotate(func)
        registered = GRPC_HANDLERS.get(signature)
        if registered is not None and registered.method is not func:
            raise ValueError(
                f"{signature.full_method} is already handled by {registered.method.__qualname__}"
            )
        GRPC_HANDLERS[signature] = annotation
        return func

    return decorator


def annotate(func: Callable[..., Any]) -> MethodAnnotation:
    """Прочитать тип вызова и классы сообщений из сигнатуры хэндлера; ошибка — `ValueError`."""
    name = getattr(func, "__qualname__", repr(func))
    parameters = list(inspect.signature(func).parameters.values())
    if [p.name for p in parameters[:2]] != ["request", "context"]:
        raise ValueError(f'Handler "{name}" must take "request" and "context" as first arguments')
    for parameter in parameters[:2]:
        if parameter.kind not in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD):
            raise ValueError(f'Argument "{parameter.name}" of "{name}" must be positional')
        if parameter.annotation is inspect.Parameter.empty:
            raise ValueError(f'Argument "{parameter.name}" of "{name}" has no type hint')
    if inspect.signature(func).return_annotation is inspect.Signature.empty:
        raise ValueError(f'Handler "{name}" has no return annotation')

    try:
        hints = get_type_hints(func)
    except NameError as exc:
        raise ValueError(f'Type hints of "{name}" cannot be resolved: {exc}') from exc

    request, client_streaming = _message_type(hints["request"], name, "request")
    response, server_streaming = _message_type(hints["return"], name, "return")

    if server_streaming and not inspect.isasyncgenfunction(func):
        raise ValueError(f'Server-streaming handler "{name}" must be an async generator')
    if not server_streaming and not inspect.iscoroutinefunction(func):
        raise ValueError(f'Handler "{name}" must be declared with "async def"')

    return MethodAnnotation(
        request=request,
        response=response,
        method=func,
        grpc_type=IN_OUT_METHOD_TYPE[(client_streaming, server_streaming)],
    )


def _message_type(hint: Any, handler: str, where: str) -> tuple[type[Message], bool]:
    """Сообщение и признак стрима: `Msg` → (Msg, False), `AsyncIterator[Msg]` → (Msg, True)."""
    streaming = get_origin(hint) in (AsyncIterator, AsyncGenerator)
    message = get_args(hint)[0] if streaming else hint
    if not (isinstance(message, type) and issubclass(message, Message)):
        raise ValueError(
            f'Type hint of "{where}" of "{handler}" must be a protobuf message '
            f"or AsyncIterator of it, got {hint!r}"
        )
    return message, streaming
