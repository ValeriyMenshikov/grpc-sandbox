"""Доменные исключения стенда и их перевод в gRPC-статус с rich details (google.rpc)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Never

import grpc
from google.protobuf import any_pb2
from google.protobuf.message import Message
from google.rpc import error_details_pb2, status_pb2
from grpc_status import rpc_status

ERROR_DOMAIN = "stand.local"


@dataclass(frozen=True)
class FieldViolation:
    field: str
    description: str


@dataclass(frozen=True)
class PreconditionViolation:
    type: str
    subject: str
    description: str


@dataclass(frozen=True)
class QuotaViolation:
    subject: str
    description: str


class StandError(Exception):
    """Базовое доменное исключение: статус-код, сообщение и details для google.rpc.Status."""

    code: grpc.StatusCode = grpc.StatusCode.UNKNOWN
    default_message: str = "Unknown error"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)

    def details(self) -> list[Message]:
        return []


class InvalidArgument(StandError):
    code = grpc.StatusCode.INVALID_ARGUMENT
    default_message = "Invalid argument"

    def __init__(
        self, field_violations: Sequence[FieldViolation] = (), message: str | None = None
    ) -> None:
        super().__init__(message)
        self.field_violations = list(field_violations)

    def details(self) -> list[Message]:
        return [
            error_details_pb2.BadRequest(
                field_violations=[
                    error_details_pb2.BadRequest.FieldViolation(
                        field=v.field, description=v.description
                    )
                    for v in self.field_violations
                ]
            )
        ]


class _ResourceError(StandError):
    def __init__(
        self,
        resource_type: str,
        resource_name: str,
        message: str | None = None,
        description: str = "",
    ) -> None:
        super().__init__(message or f"{resource_type} {resource_name!r}: {self.default_message}")
        self.resource_type = resource_type
        self.resource_name = resource_name
        self.description = description

    def details(self) -> list[Message]:
        return [
            error_details_pb2.ResourceInfo(
                resource_type=self.resource_type,
                resource_name=self.resource_name,
                description=self.description,
            )
        ]


class NotFound(_ResourceError):
    code = grpc.StatusCode.NOT_FOUND
    default_message = "not found"


class AlreadyExists(_ResourceError):
    code = grpc.StatusCode.ALREADY_EXISTS
    default_message = "already exists"


class Unauthenticated(StandError):
    code = grpc.StatusCode.UNAUTHENTICATED
    default_message = "Unauthenticated"


class PermissionDenied(StandError):
    code = grpc.StatusCode.PERMISSION_DENIED
    default_message = "Permission denied"

    def __init__(self, reason: str, message: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason

    def details(self) -> list[Message]:
        return [error_details_pb2.ErrorInfo(reason=self.reason, domain=ERROR_DOMAIN)]


class FailedPrecondition(StandError):
    code = grpc.StatusCode.FAILED_PRECONDITION
    default_message = "Failed precondition"

    def __init__(
        self, violations: Sequence[PreconditionViolation] = (), message: str | None = None
    ) -> None:
        super().__init__(message)
        self.violations = list(violations)

    def details(self) -> list[Message]:
        return [
            error_details_pb2.PreconditionFailure(
                violations=[
                    error_details_pb2.PreconditionFailure.Violation(
                        type=v.type, subject=v.subject, description=v.description
                    )
                    for v in self.violations
                ]
            )
        ]


class ResourceExhausted(StandError):
    code = grpc.StatusCode.RESOURCE_EXHAUSTED
    default_message = "Resource exhausted"

    def __init__(
        self, violations: Sequence[QuotaViolation] = (), message: str | None = None
    ) -> None:
        super().__init__(message)
        self.violations = list(violations)

    def details(self) -> list[Message]:
        return [
            error_details_pb2.QuotaFailure(
                violations=[
                    error_details_pb2.QuotaFailure.Violation(
                        subject=v.subject, description=v.description
                    )
                    for v in self.violations
                ]
            )
        ]


class DependencyUnavailable(StandError):
    """Сосед недоступен (UNAVAILABLE / DEADLINE_EXCEEDED у исходящего вызова)."""

    code = grpc.StatusCode.UNAVAILABLE
    default_message = "Dependency unavailable"
    reason = "DEPENDENCY_UNAVAILABLE"

    def __init__(self, dependency: str, message: str | None = None) -> None:
        super().__init__(message or f"{dependency} is unavailable")
        self.dependency = dependency

    def details(self) -> list[Message]:
        return [
            error_details_pb2.ErrorInfo(
                reason=self.reason,
                domain=ERROR_DOMAIN,
                metadata={"dependency": self.dependency},
            )
        ]


INTERNAL_MESSAGE = "Internal error"
DETAILS_KEY = "grpc-status-details-bin"


def error_status(error: grpc.aio.AioRpcError) -> status_pb2.Status | None:
    """google.rpc.Status из ошибки исходящего вызова; None — у ошибки нет rich details.

    `rpc_status.from_call` типизирован только под синхронный `grpc.Call`.
    """
    for key, value in error.trailing_metadata() or ():
        if key == DETAILS_KEY and isinstance(value, bytes):
            return status_pb2.Status.FromString(value)
    return None


def precondition_violations(error: grpc.aio.AioRpcError) -> list[PreconditionViolation]:
    """Нарушения из PreconditionFailure в details ошибки соседа (чтобы отдать их дальше)."""
    status = error_status(error)
    if status is None:
        return []
    violations: list[PreconditionViolation] = []
    for detail in status.details:
        failure = error_details_pb2.PreconditionFailure()
        if detail.Unpack(failure):
            violations += [
                PreconditionViolation(v.type, v.subject, v.description) for v in failure.violations
            ]
    return violations


def build_status(exc: BaseException) -> grpc.Status:
    """gRPC-статус для исключения: доменное → свой код и details, прочее → INTERNAL без деталей.

    Текст и стек прочих исключений наружу не уходят — только в лог.
    """
    if not isinstance(exc, StandError):
        return rpc_status.to_status(
            status_pb2.Status(code=grpc.StatusCode.INTERNAL.value[0], message=INTERNAL_MESSAGE)
        )
    packed = []
    for detail in exc.details():
        item = any_pb2.Any()
        item.Pack(detail)
        packed.append(item)
    return rpc_status.to_status(
        status_pb2.Status(code=exc.code.value[0], message=exc.message, details=packed)
    )


async def abort_with_error(
    context: grpc.aio.ServicerContext[Any, Any], exc: BaseException
) -> Never:
    """Завершить вызов статусом `build_status(exc)`.

    `context.abort(..., trailing_metadata)` заменяет уже выставленную trailing metadata, поэтому
    она добавляется к `grpc-status-details-bin` явно.
    """
    status = build_status(exc)
    trailing = (*(context.trailing_metadata() or ()), *status.trailing_metadata)
    await context.abort(status.code, status.details, trailing)
