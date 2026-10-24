"""Доменный User ↔ сообщения users.v1."""

from datetime import datetime

from google.protobuf.timestamp_pb2 import Timestamp
from stand_core.grpc import Role
from users.v1 import users_pb2

from user_service.models import User, UserStatus

ROLE_TO_PROTO: dict[Role, users_pb2.UserRole.ValueType] = {
    Role.BUYER: users_pb2.USER_ROLE_BUYER,
    Role.SELLER: users_pb2.USER_ROLE_SELLER,
}
# USER_ROLE_UNSPECIFIED при регистрации трактуется как покупатель
ROLE_FROM_PROTO: dict[users_pb2.UserRole.ValueType, Role] = {
    users_pb2.USER_ROLE_UNSPECIFIED: Role.BUYER,
    users_pb2.USER_ROLE_BUYER: Role.BUYER,
    users_pb2.USER_ROLE_SELLER: Role.SELLER,
}
STATUS_TO_PROTO: dict[UserStatus, users_pb2.UserStatus.ValueType] = {
    UserStatus.PENDING: users_pb2.USER_STATUS_PENDING,
    UserStatus.ACTIVE: users_pb2.USER_STATUS_ACTIVE,
}


def timestamp(value: datetime) -> Timestamp:
    result = Timestamp()
    result.FromDatetime(value)
    return result


def user_pb(user: User) -> users_pb2.User:
    message = users_pb2.User(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        role=ROLE_TO_PROTO[user.role],
        status=STATUS_TO_PROTO[user.status],
        created_at=timestamp(user.created_at),
        updated_at=timestamp(user.updated_at),
    )
    if user.phone is not None:
        message.phone = user.phone
    return message
