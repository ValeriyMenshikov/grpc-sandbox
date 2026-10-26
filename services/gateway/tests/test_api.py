"""Эндпоинты gateway с подменёнными gRPC-клиентами: запрос в gRPC, ответ в JSON, заголовки."""

from catalog.v1 import catalog_pb2
from fastapi.testclient import TestClient
from orders.v1 import orders_pb2
from users.v1 import users_pb2

from .fakes import FakeCatalog, FakeOrders, FakeUsers

BEARER = {"Authorization": "Bearer token-1"}
RUB_199_90 = {"currency_code": "RUB", "units": 199, "nanos": 900_000_000}


def test_healthz(http: TestClient) -> None:
    response = http.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_sign_up_creates_buyer_by_default(http: TestClient, users: FakeUsers) -> None:
    response = http.post("/auth/sign-up", json={"email": "b@example.com", "password": "secret-123"})

    assert response.status_code == 201
    assert response.json()["status"] == "PENDING"
    assert response.json()["role"] == "BUYER"
    request = users.record.last.args[0]
    assert isinstance(request, users_pb2.SignUpRequest)
    assert (request.email, request.password, request.role) == (
        "b@example.com",
        "secret-123",
        users_pb2.USER_ROLE_BUYER,
    )


def test_sign_up_seller(http: TestClient, users: FakeUsers) -> None:
    response = http.post(
        "/auth/sign-up",
        json={"email": "s@example.com", "password": "secret-123", "role": "SELLER"},
    )

    assert response.json()["role"] == "SELLER"
    assert users.record.last.args[0].role == users_pb2.USER_ROLE_SELLER


def test_sign_up_rejects_unknown_role(http: TestClient, users: FakeUsers) -> None:
    response = http.post(
        "/auth/sign-up", json={"email": "s@example.com", "password": "x", "role": "ADMIN"}
    )

    assert response.status_code == 422
    assert users.record.calls == []


def test_confirm(http: TestClient, users: FakeUsers) -> None:
    response = http.post("/auth/confirm", json={"email": "b@example.com", "code": "123456"})

    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE"
    request = users.record.last.args[0]
    assert (request.email, request.code) == ("b@example.com", "123456")


def test_sign_in(http: TestClient, users: FakeUsers) -> None:
    response = http.post("/auth/sign-in", json={"email": "b@example.com", "password": "pw"})

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] == "token-1"
    assert body["expires_at"] == "2026-01-01T01:00:00Z"
    assert body["user"]["user_id"] == "u-1"
    assert body["user"]["phone"] is None
    assert body["user"]["created_at"] == "2026-01-01T00:00:00Z"


def test_me_forwards_authorization(http: TestClient, users: FakeUsers) -> None:
    response = http.get("/me", headers=BEARER)

    assert response.status_code == 200
    assert response.json()["email"] == "buyer@example.com"
    assert users.record.last.authorization == "Bearer token-1"


def test_search_products_maps_query_to_request(http: TestClient, catalog: FakeCatalog) -> None:
    response = http.get(
        "/products",
        params={
            "query": "чай",
            "category": "kitchen",
            "min_price_kopecks": 100,
            "max_price_kopecks": 50_000,
            "sort": "price_desc",
            "page_size": 10,
            "page_token": "t-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["next_page_token"] == "t-2"
    assert body["products"][0]["price"] == RUB_199_90
    assert body["products"][0]["stock"] == 5
    request = catalog.record.last.args[0]
    assert isinstance(request, catalog_pb2.SearchProductsRequest)
    assert request.query == "чай"
    assert request.category == "kitchen"
    assert (request.min_price_kopecks, request.max_price_kopecks) == (100, 50_000)
    assert request.sort == catalog_pb2.SORT_ORDER_PRICE_DESC
    assert (request.pagination.page_size, request.pagination.page_token) == (10, "t-1")


def test_search_products_leaves_optional_filters_unset(
    http: TestClient, catalog: FakeCatalog
) -> None:
    http.get("/products")

    request = catalog.record.last.args[0]
    assert not request.HasField("category")
    assert not request.HasField("min_price_kopecks")
    assert not request.HasField("max_price_kopecks")
    assert request.sort == catalog_pb2.SORT_ORDER_UNSPECIFIED


def test_get_product(http: TestClient, catalog: FakeCatalog) -> None:
    response = http.get("/products/p-7")

    assert response.status_code == 200
    assert response.json()["product_id"] == "p-7"
    assert catalog.record.last.args == ("p-7",)


def test_cart_endpoints_forward_authorization(http: TestClient, orders: FakeOrders) -> None:
    got = http.get("/cart", headers=BEARER)
    added = http.post("/cart/items", json={"product_id": "p-1", "quantity": 2}, headers=BEARER)
    removed = http.delete("/cart/items/p-1", headers=BEARER)

    assert got.json()["items"][0]["unit_price"] == RUB_199_90
    assert got.json()["total"] == {"currency_code": "RUB", "units": 399, "nanos": 800_000_000}
    assert added.status_code == 200
    assert removed.json() == {
        "items": [],
        "total": {"currency_code": "RUB", "units": 0, "nanos": 0},
    }
    assert [(c.method, c.args) for c in orders.record.calls] == [
        ("GetCart", ()),
        ("AddCartItem", ("p-1", 2)),
        ("RemoveCartItem", ("p-1",)),
    ]
    assert {c.authorization for c in orders.record.calls} == {"Bearer token-1"}


def test_checkout_forwards_idempotency_key(http: TestClient, orders: FakeOrders) -> None:
    response = http.post("/checkout", headers={**BEARER, "Idempotency-Key": "key-1"})

    assert response.status_code == 200
    assert response.json()["status"] == "CREATED"
    assert orders.record.last.args == ("key-1",)


def test_checkout_without_key_lets_order_service_decide(
    http: TestClient, orders: FakeOrders
) -> None:
    http.post("/checkout", headers=BEARER)

    assert orders.record.last.args == (None,)


def test_list_orders_filters_by_status(http: TestClient, orders: FakeOrders) -> None:
    response = http.get(
        "/orders", params={"status": "DELIVERED", "page_size": 5, "page_token": "t"}
    )

    assert [o["order_id"] for o in response.json()["orders"]] == ["o-2", "o-1"]
    request = orders.record.last.args[0]
    assert isinstance(request, orders_pb2.ListOrdersRequest)
    assert request.status == orders_pb2.ORDER_STATUS_DELIVERED
    assert (request.pagination.page_size, request.pagination.page_token) == (5, "t")


def test_list_orders_without_status(http: TestClient, orders: FakeOrders) -> None:
    http.get("/orders")

    assert not orders.record.last.args[0].HasField("status")


def test_list_orders_rejects_unknown_status(http: TestClient, orders: FakeOrders) -> None:
    response = http.get("/orders", params={"status": "LOST"})

    assert response.status_code == 422
    assert orders.record.calls == []


def test_values_out_of_proto_range_are_422(
    http: TestClient, catalog: FakeCatalog, orders: FakeOrders
) -> None:
    page = http.get("/orders", params={"page_size": 2**31}, headers=BEARER)
    price = http.get("/products", params={"min_price_kopecks": 2**63})
    quantity = http.post(
        "/cart/items", json={"product_id": "p-1", "quantity": 2**63}, headers=BEARER
    )

    assert [r.status_code for r in (page, price, quantity)] == [422, 422, 422]
    assert orders.record.calls == []


def test_get_order(http: TestClient, orders: FakeOrders) -> None:
    response = http.get("/orders/o-9", headers=BEARER)

    assert response.json()["order_id"] == "o-9"
    assert response.json()["items"][0]["quantity"] == 2
    assert orders.record.last.args == ("o-9",)


def test_get_order_detail_has_history_and_steps(http: TestClient, orders: FakeOrders) -> None:
    body = http.get("/orders/o-9", headers=BEARER).json()

    assert body["delivery_steps"] == [
        "CREATED",
        "PAID",
        "ASSEMBLING",
        "HANDED_TO_COURIER",
        "DELIVERED",
    ]
    assert [change["status"] for change in body["history"]] == ["CREATED", "PAID"]
    assert body["history"][0]["changed_at"] == "2026-01-01T00:00:00Z"


def test_request_id_is_forwarded_and_returned(http: TestClient, orders: FakeOrders) -> None:
    response = http.get("/orders/o-1", headers={"X-Request-Id": "req-42"})

    assert response.headers["x-request-id"] == "req-42"
    assert orders.record.last.request_id == "req-42"


def test_request_id_is_generated_when_missing(http: TestClient, orders: FakeOrders) -> None:
    response = http.get("/orders/o-1")

    generated = response.headers["x-request-id"]
    assert generated
    assert orders.record.last.request_id == generated
    assert orders.record.last.authorization is None
