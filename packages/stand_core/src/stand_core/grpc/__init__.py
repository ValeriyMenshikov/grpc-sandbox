"""gRPC-часть stand_core: контекст вызова и доменные ошибки."""

from stand_core.grpc.context import (
    Context,
    CurrentUser,
    Role,
    current_user,
    current_user_or_none,
    request_id,
)
from stand_core.grpc.errors import (
    AlreadyExists,
    DependencyUnavailable,
    FailedPrecondition,
    FieldViolation,
    InvalidArgument,
    NotFound,
    PermissionDenied,
    PreconditionViolation,
    QuotaViolation,
    ResourceExhausted,
    StandError,
    Unauthenticated,
    build_status,
)

__all__ = (
    "AlreadyExists",
    "Context",
    "CurrentUser",
    "DependencyUnavailable",
    "FailedPrecondition",
    "FieldViolation",
    "InvalidArgument",
    "NotFound",
    "PermissionDenied",
    "PreconditionViolation",
    "QuotaViolation",
    "ResourceExhausted",
    "Role",
    "StandError",
    "Unauthenticated",
    "build_status",
    "current_user",
    "current_user_or_none",
    "request_id",
)
