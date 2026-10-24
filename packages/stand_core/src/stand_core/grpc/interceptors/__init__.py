"""Серверные интерцепторы стенда; `DEFAULT_INTERCEPTORS` — в порядке выполнения (ТЗ 5.4)."""

from stand_core.grpc.interceptors.auth import (
    AUTH_POLICIES,
    AuthInterceptor,
    AuthPolicy,
    register_auth_policies,
)
from stand_core.grpc.interceptors.base import Call, CallInterceptor
from stand_core.grpc.interceptors.exception_handling import ExceptionHandlingInterceptor
from stand_core.grpc.interceptors.logging import LoggingInterceptor
from stand_core.grpc.interceptors.request_id import RequestIdInterceptor
from stand_core.grpc.interceptors.stream_count import StreamCountInterceptor

DEFAULT_INTERCEPTORS = (
    RequestIdInterceptor,
    LoggingInterceptor,
    AuthInterceptor,
    StreamCountInterceptor,
    ExceptionHandlingInterceptor,
)

__all__ = (
    "AUTH_POLICIES",
    "DEFAULT_INTERCEPTORS",
    "AuthInterceptor",
    "AuthPolicy",
    "Call",
    "CallInterceptor",
    "ExceptionHandlingInterceptor",
    "LoggingInterceptor",
    "RequestIdInterceptor",
    "StreamCountInterceptor",
    "register_auth_policies",
)
