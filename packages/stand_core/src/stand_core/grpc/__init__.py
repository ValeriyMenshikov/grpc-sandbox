"""gRPC-часть stand_core: декоратор rpc, сервер, связка с nuke-di, контекст вызова и ошибки."""

from stand_core.grpc.context import (
    Context,
    CurrentUser,
    Role,
    current_user,
    current_user_or_none,
    request_id,
)
from stand_core.grpc.di import inject_handlers, resolve_interceptors
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
from stand_core.grpc.rpc import (
    GRPC_HANDLERS,
    GrpcTypeEnum,
    MethodAnnotation,
    MethodSignature,
    rpc,
)
from stand_core.grpc.server import ProtoMismatchError, RunningServer, grpc_server

__all__ = (
    "GRPC_HANDLERS",
    "AlreadyExists",
    "Context",
    "CurrentUser",
    "DependencyUnavailable",
    "FailedPrecondition",
    "FieldViolation",
    "GrpcTypeEnum",
    "InvalidArgument",
    "MethodAnnotation",
    "MethodSignature",
    "NotFound",
    "PermissionDenied",
    "PreconditionViolation",
    "ProtoMismatchError",
    "QuotaViolation",
    "ResourceExhausted",
    "Role",
    "RunningServer",
    "StandError",
    "Unauthenticated",
    "build_status",
    "current_user",
    "current_user_or_none",
    "grpc_server",
    "inject_handlers",
    "request_id",
    "resolve_interceptors",
    "rpc",
)
