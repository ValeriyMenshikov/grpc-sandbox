"""catalog-service целиком на in-process сервере: v1 и v2 на одном порту, интерцепторы, details."""

from collections.abc import AsyncIterator, Iterator

import catalog_service.handlers  # noqa: F401  — регистрирует хэндлеры
import grpc
import pytest
from catalog.v1 import catalog_pb2 as v1
from catalog.v1 import catalog_pb2_grpc as v1_grpc
from catalog.v2 import catalog_pb2 as v2
from catalog.v2 import catalog_pb2_grpc as v2_grpc
from catalog_service.auth import AUTH_POLICIES
from catalog_service.repository import CatalogRepository
from common.v1 import money_pb2
from google.rpc import error_details_pb2
from grpc_reflection.v1alpha import reflection_pb2
from nuke_di import Dependencies
from stand_core.clients.sessions import Sessions
from stand_core.grpc import GRPC_HANDLERS, CurrentUser, Role, inject_handlers
from stand_core.grpc.interceptors import (
    AUTH_POLICIES as REGISTERED_POLICIES,
)
from stand_core.grpc.interceptors import (
    AuthInterceptor,
    ExceptionHandlingInterceptor,
    LoggingInterceptor,
    RequestIdInterceptor,
    StreamCountInterceptor,
    register_auth_policies,
)
from stand_core.grpc.server import RunningServer, grpc_server
from stand_core.settings import Settings
from stand_core.testing import rich_status

from .conftest import API_KEY
from .fakes import BUYER_ID, SELLER_ID, FakeRepository

SELLER_TOKEN = "seller-token"
BUYER_TOKEN = "buyer-token"
SELLER = (("x-api-key", API_KEY), ("authorization", f"Bearer {SELLER_TOKEN}"))
BUYER = (("x-api-key", API_KEY), ("authorization", f"Bearer {BUYER_TOKEN}"))
SERVICE = (("x-api-key", API_KEY),)


class FakeSessions(Sessions):
    def __init__(self) -> None:
        self.users = {
            SELLER_TOKEN: CurrentUser(SELLER_ID, Role.SELLER),
            BUYER_TOKEN: CurrentUser(BUYER_ID, Role.BUYER),
        }

    async def get(self, token: str) -> CurrentUser | None:
        return self.users.get(token)


@pytest.fixture
def policies() -> Iterator[None]:
    saved = dict(REGISTERED_POLICIES)
    register_auth_policies(AUTH_POLICIES)
    yield
    REGISTERED_POLICIES.clear()
    REGISTERED_POLICIES.update(saved)


@pytest.fixture
async def running(repository: FakeRepository, policies: None) -> AsyncIterator[RunningServer]:
    container = Dependencies()
    container.mock(CatalogRepository, repository)
    catalog_handlers = {
        signature: annotation
        for signature, annotation in GRPC_HANDLERS.items()
        if signature.package.startswith("catalog.")
    }
    handlers = inject_handlers(catalog_handlers, container)
    interceptors = [
        RequestIdInterceptor(),
        LoggingInterceptor(),
        AuthInterceptor(Settings(), FakeSessions()),
        StreamCountInterceptor(),
        ExceptionHandlingInterceptor(),
    ]
    async with (
        container,
        grpc_server(handlers, interceptors, port=0, host="localhost", grace=0) as server,
    ):
        yield server


@pytest.fixture
async def channel(running: RunningServer) -> AsyncIterator[grpc.aio.Channel]:
    async with grpc.aio.insecure_channel(f"localhost:{running.port}") as channel:
        yield channel


async def test_v1_and_v2_served_on_one_port(
    channel: grpc.aio.Channel, repository: FakeRepository
) -> None:
    product = repository.add("EL-1", "Наушники", price_kopecks=899_000)

    from_v1 = await v1_grpc.CatalogServiceStub(channel).GetProduct(
        v1.GetProductRequest(product_id=product.product_id), metadata=SERVICE
    )
    from_v2 = await v2_grpc.CatalogServiceStub(channel).SearchProducts(
        v2.SearchProductsRequest(region_id="msk"), metadata=SERVICE
    )

    assert from_v1.product.price_kopecks == 899_000
    assert [p.price.units for p in from_v2.products] == [8990]


async def test_reflection_lists_both_versions(channel: grpc.aio.Channel) -> None:
    reflect = channel.stream_stream(
        "/grpc.reflection.v1alpha.ServerReflection/ServerReflectionInfo",
        request_serializer=reflection_pb2.ServerReflectionRequest.SerializeToString,
        response_deserializer=reflection_pb2.ServerReflectionResponse.FromString,
    )
    call = reflect(iter([reflection_pb2.ServerReflectionRequest(list_services="")]))
    response = await call.read()
    assert isinstance(response, reflection_pb2.ServerReflectionResponse)

    services = {service.name for service in response.list_services_response.service}
    assert {"catalog.v1.CatalogService", "catalog.v2.CatalogService"} <= services
    call.cancel()


async def test_without_api_key_is_unauthenticated(channel: grpc.aio.Channel) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await v1_grpc.CatalogServiceStub(channel).GetProduct(v1.GetProductRequest(product_id="p"))
    assert info.value.code() is grpc.StatusCode.UNAUTHENTICATED


async def test_not_found_has_resource_info(channel: grpc.aio.Channel) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await v1_grpc.CatalogServiceStub(channel).GetProduct(
            v1.GetProductRequest(product_id="missing"), metadata=SERVICE
        )

    assert info.value.code() is grpc.StatusCode.NOT_FOUND
    resource = error_details_pb2.ResourceInfo()
    assert rich_status(info.value).details[0].Unpack(resource)
    assert (resource.resource_type, resource.resource_name) == ("product", "missing")


async def test_invalid_page_token_has_bad_request(channel: grpc.aio.Channel) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await v1_grpc.CatalogServiceStub(channel).SearchProducts(
            v1.SearchProductsRequest(pagination=money_pb2.Pagination(page_token="garbage")),
            metadata=SERVICE,
        )

    assert info.value.code() is grpc.StatusCode.INVALID_ARGUMENT
    bad_request = error_details_pb2.BadRequest()
    assert rich_status(info.value).details[0].Unpack(bad_request)
    assert bad_request.field_violations[0].field == "pagination.page_token"


async def test_v2_search_without_region_is_invalid(channel: grpc.aio.Channel) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await v2_grpc.CatalogServiceStub(channel).SearchProducts(
            v2.SearchProductsRequest(), metadata=SERVICE
        )
    assert info.value.code() is grpc.StatusCode.INVALID_ARGUMENT


def import_stream(rows: int, *, bad: bool = False) -> Iterator[v1.ImportProductsRequest]:
    yield v1.ImportProductsRequest(header=v1.ImportHeader(mode=v1.IMPORT_MODE_UPSERT))
    for index in range(rows):
        yield v1.ImportProductsRequest(
            row=v1.ImportRow(
                offer_id=f"OF-{index}",
                name=f"Товар {index}",
                category="books",
                price_kopecks=0 if bad and index == 0 else 1000,
                stock=1,
            )
        )


async def test_import_then_export_as_seller(
    channel: grpc.aio.Channel, repository: FakeRepository
) -> None:
    stub = v1_grpc.CatalogServiceStub(channel)

    report = await stub.ImportProducts(import_stream(3, bad=True), metadata=SELLER)
    export = stub.ExportProducts(v1.ExportProductsRequest(), metadata=SELLER)
    exported = [message.product.offer_id async for message in export]

    assert (report.created, report.failed) == (2, 1)
    assert report.errors[0].field == "price_kopecks"
    assert exported == ["OF-1", "OF-2"]
    assert all(p.seller_id == SELLER_ID for p in repository.products.values())
    assert ("x-items-count", "2") in tuple(await export.trailing_metadata() or ())


async def test_import_over_limit_has_quota_failure(channel: grpc.aio.Channel) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await v1_grpc.CatalogServiceStub(channel).ImportProducts(import_stream(6), metadata=SELLER)

    assert info.value.code() is grpc.StatusCode.RESOURCE_EXHAUSTED
    quota = error_details_pb2.QuotaFailure()
    assert rich_status(info.value).details[0].Unpack(quota)
    assert quota.violations[0].subject == f"seller:{SELLER_ID}"


async def test_import_without_header_is_invalid(channel: grpc.aio.Channel) -> None:
    rows = iter([v1.ImportProductsRequest(row=v1.ImportRow(offer_id="OF-1"))])
    with pytest.raises(grpc.aio.AioRpcError) as info:
        await v1_grpc.CatalogServiceStub(channel).ImportProducts(rows, metadata=SELLER)
    assert info.value.code() is grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.parametrize("metadata", [BUYER, SERVICE])
async def test_seller_methods_reject_others(
    channel: grpc.aio.Channel, metadata: tuple[tuple[str, str], ...]
) -> None:
    stub = v1_grpc.CatalogServiceStub(channel)
    with pytest.raises(grpc.aio.AioRpcError) as import_info:
        await stub.ImportProducts(import_stream(1), metadata=metadata)
    with pytest.raises(grpc.aio.AioRpcError) as export_info:
        async for _ in stub.ExportProducts(v1.ExportProductsRequest(), metadata=metadata):
            pass

    expected = (
        grpc.StatusCode.PERMISSION_DENIED if metadata is BUYER else grpc.StatusCode.UNAUTHENTICATED
    )
    assert import_info.value.code() is expected
    assert export_info.value.code() is expected
