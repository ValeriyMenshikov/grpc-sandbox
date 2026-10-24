"""Доменные сообщения чата → сообщения support.v1."""

from datetime import datetime

from google.protobuf.timestamp_pb2 import Timestamp
from support.v1 import support_pb2

from support_service.models import Author, ChatMessage

AUTHOR_TO_PROTO: dict[Author, support_pb2.Author.ValueType] = {
    Author.CUSTOMER: support_pb2.AUTHOR_CUSTOMER,
    Author.AGENT: support_pb2.AUTHOR_AGENT,
    Author.BOT: support_pb2.AUTHOR_BOT,
}


def timestamp(value: datetime) -> Timestamp:
    result = Timestamp()
    result.FromDatetime(value)
    return result


def message_pb(message: ChatMessage) -> support_pb2.ChatMessage:
    return support_pb2.ChatMessage(
        message_id=message.message_id,
        author=AUTHOR_TO_PROTO[message.author],
        text=message.text,
        created_at=timestamp(message.created_at),
    )


def message_event(message: ChatMessage) -> support_pb2.ChatResponse:
    return support_pb2.ChatResponse(message=message_pb(message))
