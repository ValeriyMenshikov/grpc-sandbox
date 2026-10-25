"""Контракты из protos/: сгенерированный код импортируется, сервисы и методы на месте."""

import importlib

import pytest
from catalog.v2 import catalog_pb2 as catalog_v2_pb2
from google.protobuf import descriptor_pb2, descriptor_pool
from google.protobuf.descriptor import FieldDescriptor, MethodDescriptor

PB2_MODULES = [
    "common.v1.money_pb2",
    "users.v1.users_pb2",
    "users.v1.users_pb2_grpc",
    "catalog.v1.catalog_pb2",
    "catalog.v1.catalog_pb2_grpc",
    "catalog.v2.catalog_pb2",
    "catalog.v2.catalog_pb2_grpc",
    "orders.v1.orders_pb2",
    "orders.v1.orders_pb2_grpc",
    "support.v1.support_pb2",
    "support.v1.support_pb2_grpc",
    "notifications.v1.notifications_pb2",
    "notifications.v1.notifications_pb2_grpc",
]

UNARY = (False, False)
CLIENT_STREAM = (True, False)
SERVER_STREAM = (False, True)
BIDI = (True, True)

# service full name -> {method: (client_streaming, server_streaming)}
EXPECTED_SERVICES: dict[str, dict[str, tuple[bool, bool]]] = {
    "users.v1.UserService": {
        "SignUp": UNARY,
        "ConfirmEmail": UNARY,
        "SignIn": UNARY,
        "SignOut": UNARY,
        "GetMe": UNARY,
        "UpdateProfile": UNARY,
        "LegacyResetPassword": UNARY,
    },
    "catalog.v1.CatalogService": {
        "GetProduct": UNARY,
        "SearchProducts": UNARY,
        "ImportProducts": CLIENT_STREAM,
        "ExportProducts": SERVER_STREAM,
    },
    "catalog.v1.StockService": {
        "GetStock": UNARY,
        "ReserveStock": UNARY,
        "ReleaseStock": UNARY,
    },
    "catalog.v2.CatalogService": {
        "GetProduct": UNARY,
        "SearchProducts": UNARY,
    },
    "orders.v1.OrderService": {
        "AddCartItem": UNARY,
        "RemoveCartItem": UNARY,
        "GetCart": UNARY,
        "Checkout": UNARY,
        "GetOrder": UNARY,
        "ListOrders": UNARY,
        "CancelOrder": UNARY,
        "TrackOrder": SERVER_STREAM,
    },
    "support.v1.SupportService": {
        "Chat": BIDI,
        "GetChatHistory": UNARY,
    },
    "notifications.v1.NotificationService": {
        "ListNotifications": UNARY,
    },
}


@pytest.fixture(scope="module", autouse=True)
def _import_all() -> None:
    for name in PB2_MODULES:
        importlib.import_module(name)


def _method(service: str, method: str) -> MethodDescriptor:
    svc = descriptor_pool.Default().FindServiceByName(service)
    return svc.methods_by_name[method]


def _message_type_name(field: FieldDescriptor) -> str:
    assert field.message_type is not None, f"{field.full_name} — не message-поле"
    return field.message_type.full_name


@pytest.mark.parametrize("module", PB2_MODULES)
def test_module_importable(module: str) -> None:
    assert importlib.import_module(module) is not None


@pytest.mark.parametrize("service", sorted(EXPECTED_SERVICES))
def test_service_has_exactly_expected_methods(service: str) -> None:
    svc = descriptor_pool.Default().FindServiceByName(service)
    assert set(svc.methods_by_name) == set(EXPECTED_SERVICES[service])


@pytest.mark.parametrize(
    ("service", "method", "streaming"),
    [
        (service, method, streaming)
        for service, methods in EXPECTED_SERVICES.items()
        for method, streaming in methods.items()
    ],
)
def test_method_streaming_flags_and_naming(
    service: str, method: str, streaming: tuple[bool, bool]
) -> None:
    md = _method(service, method)
    assert (md.client_streaming, md.server_streaming) == streaming
    package = service.rsplit(".", 1)[0]
    assert md.input_type.full_name == f"{package}.{method}Request"
    assert md.output_type.full_name == f"{package}.{method}Response"


def test_money_fields() -> None:
    money = descriptor_pool.Default().FindMessageTypeByName("common.v1.Money")
    assert {f.name for f in money.fields} == {"units", "nanos", "currency_code"}
    pagination = descriptor_pool.Default().FindMessageTypeByName("common.v1.Pagination")
    assert {f.name for f in pagination.fields} == {"page_size", "page_token"}


def test_catalog_v1_price_is_kopecks() -> None:
    product = descriptor_pool.Default().FindMessageTypeByName("catalog.v1.Product")
    field = product.fields_by_name["price_kopecks"]
    assert field.type == FieldDescriptor.TYPE_INT64


def test_catalog_v2_price_is_money_under_new_number_without_reserved() -> None:
    v1 = descriptor_pool.Default().FindMessageTypeByName("catalog.v1.Product")
    v2 = descriptor_pool.Default().FindMessageTypeByName("catalog.v2.Product")
    assert "price_kopecks" not in v2.fields_by_name
    price = v2.fields_by_name["price"]
    assert _message_type_name(price) == "common.v1.Money"
    assert price.number != v1.fields_by_name["price_kopecks"].number
    # Номер удалённого поля не зарезервирован — намеренная ловушка для уроков про buf breaking
    file_proto = descriptor_pb2.FileDescriptorProto.FromString(
        catalog_v2_pb2.DESCRIPTOR.serialized_pb
    )
    product_proto = next(m for m in file_proto.message_type if m.name == "Product")
    assert not product_proto.reserved_range
    assert not product_proto.reserved_name


def test_catalog_v2_search_has_region_id() -> None:
    req = descriptor_pool.Default().FindMessageTypeByName("catalog.v2.SearchProductsRequest")
    assert req.fields_by_name["region_id"].type == FieldDescriptor.TYPE_STRING


def test_import_request_header_in_oneof() -> None:
    req = descriptor_pool.Default().FindMessageTypeByName("catalog.v1.ImportProductsRequest")
    oneof = req.oneofs_by_name["payload"]
    assert {f.name for f in oneof.fields} == {"header", "row"}
    modes = descriptor_pool.Default().FindEnumTypeByName("catalog.v1.ImportMode")
    assert {"IMPORT_MODE_UPSERT", "IMPORT_MODE_CREATE_ONLY"} <= set(modes.values_by_name)


def test_export_has_updated_since() -> None:
    req = descriptor_pool.Default().FindMessageTypeByName("catalog.v1.ExportProductsRequest")
    assert _message_type_name(req.fields_by_name["updated_since"]) == ("google.protobuf.Timestamp")


def test_order_statuses() -> None:
    status = descriptor_pool.Default().FindEnumTypeByName("orders.v1.OrderStatus")
    assert [v.name for v in status.values] == [
        "ORDER_STATUS_UNSPECIFIED",
        "ORDER_STATUS_CREATED",
        "ORDER_STATUS_PAID",
        "ORDER_STATUS_ASSEMBLING",
        "ORDER_STATUS_HANDED_TO_COURIER",
        "ORDER_STATUS_DELIVERED",
        "ORDER_STATUS_CANCELLED",
    ]


def test_users_roles_and_field_mask() -> None:
    pool = descriptor_pool.Default()
    roles = pool.FindEnumTypeByName("users.v1.UserRole")
    assert {"USER_ROLE_BUYER", "USER_ROLE_SELLER"} <= set(roles.values_by_name)
    statuses = pool.FindEnumTypeByName("users.v1.UserStatus")
    assert {"USER_STATUS_PENDING", "USER_STATUS_ACTIVE"} <= set(statuses.values_by_name)
    req = pool.FindMessageTypeByName("users.v1.UpdateProfileRequest")
    assert _message_type_name(req.fields_by_name["update_mask"]) == "google.protobuf.FieldMask"


def test_support_chat_oneofs() -> None:
    pool = descriptor_pool.Default()
    incoming = pool.FindMessageTypeByName("support.v1.ChatRequest").oneofs_by_name["payload"]
    assert {f.name for f in incoming.fields} == {"join", "message", "read"}
    outgoing = pool.FindMessageTypeByName("support.v1.ChatResponse").oneofs_by_name["payload"]
    assert {f.name for f in outgoing.fields} == {"joined", "ack", "message", "agent_typing"}


def test_notifications_list_request_and_statuses() -> None:
    pool = descriptor_pool.Default()
    status = pool.FindEnumTypeByName("notifications.v1.NotificationStatus")
    assert [v.name for v in status.values] == [
        "NOTIFICATION_STATUS_UNSPECIFIED",
        "NOTIFICATION_STATUS_SENT",
        "NOTIFICATION_STATUS_FAILED",
    ]
    req = pool.FindMessageTypeByName("notifications.v1.ListNotificationsRequest")
    assert req.fields_by_name["to_email"].has_presence
    assert _message_type_name(req.fields_by_name["pagination"]) == "common.v1.Pagination"
    notification = pool.FindMessageTypeByName("notifications.v1.Notification")
    assert {f.name for f in notification.fields} == {
        "notification_id",
        "to_email",
        "subject",
        "status",
        "error",
        "created_at",
    }
