"""Маппинг ошибок gRPC в HTTP: код, тело с details, DependencyUnavailable → 503."""

import grpc
import pytest
from fastapi.testclient import TestClient
from gateway.errors import HTTP_STATUS, http_status
from stand_core.grpc import (
    DependencyUnavailable,
    FailedPrecondition,
    FieldViolation,
    InvalidArgument,
    NotFound,
    PreconditionViolation,
    Unauthenticated,
)

from .fakes import FakeCatalog, FakeOrders, FakeUsers, rpc_error


def test_every_status_code_has_http_status() -> None:
    assert set(HTTP_STATUS) == set(grpc.StatusCode)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (grpc.StatusCode.INVALID_ARGUMENT, 400),
        (grpc.StatusCode.UNAUTHENTICATED, 401),
        (grpc.StatusCode.PERMISSION_DENIED, 403),
        (grpc.StatusCode.NOT_FOUND, 404),
        (grpc.StatusCode.ALREADY_EXISTS, 409),
        (grpc.StatusCode.FAILED_PRECONDITION, 400),
        (grpc.StatusCode.RESOURCE_EXHAUSTED, 429),
        (grpc.StatusCode.UNKNOWN, 500),
        (grpc.StatusCode.INTERNAL, 500),
        (grpc.StatusCode.UNAVAILABLE, 503),
        (grpc.StatusCode.DEADLINE_EXCEEDED, 504),
    ],
)
def test_http_status(code: grpc.StatusCode, expected: int) -> None:
    assert http_status(code) == expected


def test_not_found_from_catalog(http: TestClient, catalog: FakeCatalog) -> None:
    catalog.record.error = rpc_error(NotFound("product", "p-404"))

    response = http.get("/products/p-404")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert "p-404" in error["message"]
    assert error["details"] == [
        {
            "@type": "type.googleapis.com/google.rpc.ResourceInfo",
            "resource_type": "product",
            "resource_name": "p-404",
        }
    ]


def test_invalid_argument_keeps_field_violations(http: TestClient, users: FakeUsers) -> None:
    users.record.error = rpc_error(
        InvalidArgument([FieldViolation("password", "too short")], "Invalid sign up")
    )

    response = http.post("/auth/sign-up", json={"email": "b@example.com", "password": "x"})

    assert response.status_code == 400
    assert response.json()["error"]["details"] == [
        {
            "@type": "type.googleapis.com/google.rpc.BadRequest",
            "field_violations": [{"field": "password", "description": "too short"}],
        }
    ]


def test_unauthenticated_sets_www_authenticate(http: TestClient, users: FakeUsers) -> None:
    users.record.error = rpc_error(Unauthenticated())

    response = http.get("/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_insufficient_stock_on_checkout(http: TestClient, orders: FakeOrders) -> None:
    orders.record.error = rpc_error(
        FailedPrecondition([PreconditionViolation("INSUFFICIENT_STOCK", "p-1", "only 1 left")])
    )

    response = http.post("/checkout", headers={"Idempotency-Key": "k"})

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "FAILED_PRECONDITION"
    assert error["details"][0]["violations"] == [
        {"type": "INSUFFICIENT_STOCK", "subject": "p-1", "description": "only 1 left"}
    ]


def test_rpc_error_without_details(http: TestClient, orders: FakeOrders) -> None:
    orders.record.error = grpc.aio.AioRpcError(
        grpc.StatusCode.PERMISSION_DENIED,
        grpc.aio.Metadata(),
        grpc.aio.Metadata(),
        details="Sellers only",
    )

    response = http.get("/orders")

    assert response.status_code == 403
    assert response.json() == {
        "error": {"code": "PERMISSION_DENIED", "message": "Sellers only", "details": []}
    }


def test_dependency_unavailable_is_503(http: TestClient, orders: FakeOrders) -> None:
    orders.record.error = DependencyUnavailable("orders")

    response = http.get("/cart")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "UNAVAILABLE"
    assert error["details"] == [
        {
            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
            "reason": "DEPENDENCY_UNAVAILABLE",
            "domain": "stand.local",
            "metadata": {"dependency": "orders"},
        }
    ]


def test_unknown_detail_type_keeps_type_url() -> None:
    from gateway.errors import detail_json
    from google.protobuf import any_pb2

    detail = any_pb2.Any(type_url="type.googleapis.com/acme.Unknown", value=b"\x08\x01")

    assert detail_json(detail) == {"@type": "type.googleapis.com/acme.Unknown"}
