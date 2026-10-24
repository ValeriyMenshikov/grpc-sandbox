"""GetChatHistory напрямую: пагинация, чужой и отсутствующий чат."""

from unittest.mock import Mock

import pytest
from common.v1 import money_pb2
from stand_core.grpc import InvalidArgument, NotFound
from support.v1 import support_pb2
from support_service.handlers.get_chat_history_u_u import get_chat_history
from support_service.models import Author

from .fakes import BUYER_ID, OTHER_ID, FakeRepository

pytestmark = pytest.mark.usefixtures("buyer")


def request(
    order_id: str, page_size: int = 0, page_token: str = ""
) -> support_pb2.GetChatHistoryRequest:
    return support_pb2.GetChatHistoryRequest(
        order_id=order_id,
        pagination=money_pb2.Pagination(page_size=page_size, page_token=page_token),
    )


async def test_pages_oldest_first(context: Mock, repository: FakeRepository) -> None:
    chat = await repository.get_or_create_chat("o-1", BUYER_ID)
    for index in range(5):
        await repository.add_message(chat.chat_id, Author.CUSTOMER, f"m{index}")
    await repository.add_message(chat.chat_id, Author.BOT, "ответ")

    first = await get_chat_history(request("o-1", page_size=4), context, repository)
    second = await get_chat_history(
        request("o-1", page_size=4, page_token=first.next_page_token), context, repository
    )

    assert first.chat_id == chat.chat_id
    assert [m.text for m in first.messages] == ["m0", "m1", "m2", "m3"]
    assert [m.text for m in second.messages] == ["m4", "ответ"]
    assert second.messages[1].author == support_pb2.AUTHOR_BOT
    assert second.next_page_token == ""


async def test_foreign_or_missing_chat_is_not_found(
    context: Mock, repository: FakeRepository
) -> None:
    await repository.get_or_create_chat("o-2", OTHER_ID)

    for order_id in ("o-2", "missing"):
        with pytest.raises(NotFound):
            await get_chat_history(request(order_id), context, repository)


@pytest.mark.parametrize(
    "bad",
    [request(""), request("o-1", page_size=-1), request("o-1", page_token="garbage")],
)
async def test_invalid_request_is_invalid_argument(
    context: Mock, repository: FakeRepository, bad: support_pb2.GetChatHistoryRequest
) -> None:
    await repository.get_or_create_chat("o-1", BUYER_ID)

    with pytest.raises(InvalidArgument):
        await get_chat_history(bad, context, repository)
