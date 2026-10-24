from stand_core import Context, rpc
from stand_core.grpc import FieldViolation, InvalidArgument, NotFound, current_user
from support.v1 import support_pb2

from support_service.convert import message_pb
from support_service.pagination import decode_page_token, encode_page_token, page_size
from support_service.repository import ChatRepository


@rpc("GetChatHistory", package="support.v1", service="SupportService")
async def get_chat_history(
    request: support_pb2.GetChatHistoryRequest,
    context: Context,
    repository: ChatRepository,
) -> support_pb2.GetChatHistoryResponse:
    """История чата, старые первыми. Чата нет или он чужой — NOT_FOUND (неразличимы)."""
    if not request.order_id:
        raise InvalidArgument([FieldViolation("order_id", "must not be empty")])
    limit = page_size(request.pagination.page_size)
    offset = decode_page_token(request.pagination.page_token)
    chat = await repository.find_chat(request.order_id)
    if chat is None or chat.user_id != current_user().id:
        raise NotFound("chat", request.order_id)
    # На одну запись больше лимита — признак следующей страницы
    messages = await repository.list_messages(chat.chat_id, offset, limit + 1)
    return support_pb2.GetChatHistoryResponse(
        chat_id=chat.chat_id,
        messages=[message_pb(message) for message in messages[:limit]],
        next_page_token=encode_page_token(offset + limit) if len(messages) > limit else "",
    )
