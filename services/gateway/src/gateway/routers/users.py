"""Регистрация, вход и профиль: эндпоинты поверх users-service."""

from fastapi import status
from nuke_di.fastapi import ClientRouter
from users.v1 import users_pb2

from gateway import schemas
from gateway.clients import UsersClient

router = ClientRouter(tags=["users"])

ROLES: dict[schemas.Role, users_pb2.UserRole.ValueType] = {
    "BUYER": users_pb2.USER_ROLE_BUYER,
    "SELLER": users_pb2.USER_ROLE_SELLER,
}


@router.post("/auth/sign-up", status_code=status.HTTP_201_CREATED)
async def sign_up(body: schemas.SignUpIn, users: UsersClient) -> schemas.User:
    response = await users.sign_up(
        users_pb2.SignUpRequest(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            role=ROLES[body.role],
        )
    )
    return schemas.user(response.user)


@router.post("/auth/confirm")
async def confirm(body: schemas.ConfirmIn, users: UsersClient) -> schemas.User:
    response = await users.confirm_email(
        users_pb2.ConfirmEmailRequest(email=body.email, code=body.code)
    )
    return schemas.user(response.user)


@router.post("/auth/sign-in")
async def sign_in(body: schemas.SignInIn, users: UsersClient) -> schemas.SignInOut:
    response = await users.sign_in(
        users_pb2.SignInRequest(email=body.email, password=body.password)
    )
    return schemas.sign_in(response)


@router.get("/me")
async def me(users: UsersClient) -> schemas.User:
    response = await users.get_me()
    return schemas.user(response.user)
