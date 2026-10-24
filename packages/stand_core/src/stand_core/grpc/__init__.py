"""gRPC-часть stand_core: rpc, сервер, интерцепторы, связка с nuke-di, контекст вызова и ошибки."""

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
    abort_with_error,
    build_status,
    error_status,
    precondition_violations,
)
from stand_core.grpc.interceptors import AuthPolicy, register_auth_policies
from stand_core.grpc.interceptors.base import metadata_value
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
    "AuthPolicy",
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
    "abort_with_error",
    "build_status",
    "current_user",
    "current_user_or_none",
    "error_status",
    "grpc_server",
    "inject_handlers",
    "metadata_value",
    "precondition_violations",
    "register_auth_policies",
    "request_id",
    "resolve_interceptors",
    "rpc",
)
