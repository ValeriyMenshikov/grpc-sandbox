import grpc
import pytest
from google.protobuf.message import Message
from google.rpc import error_details_pb2, status_pb2
from stand_core.grpc.errors import (
    INTERNAL_MESSAGE,
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

STATUS_DETAILS_KEY = "grpc-status-details-bin"


def unpack_status(status: grpc.Status) -> status_pb2.Status:
    metadata = dict(status.trailing_metadata)
    raw = metadata[STATUS_DETAILS_KEY]
    assert isinstance(raw, bytes)
    return status_pb2.Status.FromString(raw)


@pytest.mark.parametrize(
    ("exc", "code", "detail_type"),
    [
        (
            InvalidArgument([FieldViolation("email", "invalid email")]),
            grpc.StatusCode.INVALID_ARGUMENT,
            error_details_pb2.BadRequest,
        ),
        (NotFound("product", "42"), grpc.StatusCode.NOT_FOUND, error_details_pb2.ResourceInfo),
        (
            AlreadyExists("user", "a@b.c"),
            grpc.StatusCode.ALREADY_EXISTS,
            error_details_pb2.ResourceInfo,
        ),
        (
            PermissionDenied("SELLER_ROLE_REQUIRED"),
            grpc.StatusCode.PERMISSION_DENIED,
            error_details_pb2.ErrorInfo,
        ),
        (
            FailedPrecondition([PreconditionViolation("STOCK", "product/1", "not enough")]),
            grpc.StatusCode.FAILED_PRECONDITION,
            error_details_pb2.PreconditionFailure,
        ),
        (
            ResourceExhausted([QuotaViolation("import", "max 1000 rows")]),
            grpc.StatusCode.RESOURCE_EXHAUSTED,
            error_details_pb2.QuotaFailure,
        ),
        (
            DependencyUnavailable("catalog"),
            grpc.StatusCode.UNAVAILABLE,
            error_details_pb2.ErrorInfo,
        ),
    ],
)
def test_domain_error_maps_to_status_with_details(
    exc: StandError, code: grpc.StatusCode, detail_type: type[Message]
) -> None:
    status = build_status(exc)

    assert status.code == code
    assert status.details == exc.message
    rich = unpack_status(status)
    assert rich.code == code.value[0]
    assert rich.message == exc.message
    assert len(rich.details) == 1
    assert rich.details[0].Unpack(detail_type())


def test_unauthenticated_has_no_details() -> None:
    status = build_status(Unauthenticated())

    assert status.code == grpc.StatusCode.UNAUTHENTICATED
    assert list(unpack_status(status).details) == []


def test_unknown_exception_is_internal_without_leaking_text() -> None:
    status = build_status(ValueError("db password is hunter2"))

    assert status.code == grpc.StatusCode.INTERNAL
    assert status.details == INTERNAL_MESSAGE
    assert list(unpack_status(status).details) == []


def test_bad_request_contains_field_violations() -> None:
    exc = InvalidArgument(
        [FieldViolation("email", "invalid"), FieldViolation("password", "too short")]
    )

    detail = error_details_pb2.BadRequest()
    unpack_status(build_status(exc)).details[0].Unpack(detail)

    assert [(v.field, v.description) for v in detail.field_violations] == [
        ("email", "invalid"),
        ("password", "too short"),
    ]


def test_permission_denied_error_info() -> None:
    detail = error_details_pb2.ErrorInfo()
    unpack_status(build_status(PermissionDenied("SELLER_ROLE_REQUIRED"))).details[0].Unpack(detail)

    assert detail.reason == "SELLER_ROLE_REQUIRED"
    assert detail.domain == "stand.local"


def test_dependency_unavailable_names_dependency() -> None:
    detail = error_details_pb2.ErrorInfo()
    unpack_status(build_status(DependencyUnavailable("catalog"))).details[0].Unpack(detail)

    assert detail.reason == "DEPENDENCY_UNAVAILABLE"
    assert detail.metadata["dependency"] == "catalog"


def test_precondition_and_quota_violations() -> None:
    precondition = error_details_pb2.PreconditionFailure()
    exc = FailedPrecondition([PreconditionViolation("STOCK", "product/1", "need 3, have 1")])
    unpack_status(build_status(exc)).details[0].Unpack(precondition)
    quota = error_details_pb2.QuotaFailure()
    exhausted = ResourceExhausted([QuotaViolation("import_rows", "limit 1000")])
    unpack_status(build_status(exhausted)).details[0].Unpack(quota)

    assert precondition.violations[0].subject == "product/1"
    assert precondition.violations[0].type == "STOCK"
    assert quota.violations[0].subject == "import_rows"


def test_resource_info_fields() -> None:
    detail = error_details_pb2.ResourceInfo()
    unpack_status(build_status(NotFound("order", "o-1"))).details[0].Unpack(detail)

    assert (detail.resource_type, detail.resource_name) == ("order", "o-1")
