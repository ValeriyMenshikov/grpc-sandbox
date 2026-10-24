"""Репозиторий, коды подтверждения и сессии в памяти для unit-тестов (без Postgres и Redis)."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from stand_core.clients import Sessions
from stand_core.grpc import CurrentUser, Role
from user_service.confirm_codes import ConfirmCodes
from user_service.models import ProfileField, User, UserStatus
from user_service.passwords import hash_password
from user_service.repository import UserRepository

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
PASSWORD = "correct-horse"


class FakeRepository(UserRepository):
    def __init__(self) -> None:
        self.users: dict[str, User] = {}
        self._clock = EPOCH

    async def connect(self) -> None:
        pass

    def tick(self) -> datetime:
        self._clock += timedelta(minutes=1)
        return self._clock

    def add(
        self,
        email: str,
        *,
        password: str = PASSWORD,
        status: UserStatus = UserStatus.ACTIVE,
        role: Role = Role.BUYER,
        display_name: str = "Покупатель",
        phone: str | None = None,
    ) -> User:
        now = self.tick()
        user = User(
            user_id=f"u-{len(self.users) + 1}",
            email=email,
            display_name=display_name,
            phone=phone,
            role=role,
            status=status,
            password_hash=hash_password(password),
            created_at=now,
            updated_at=now,
        )
        self.users[user.user_id] = user
        return user

    def by_email(self, email: str) -> User | None:
        return next((user for user in self.users.values() if user.email == email), None)

    async def create_user(
        self, email: str, password_hash: str, display_name: str, role: Role
    ) -> User | None:
        if self.by_email(email) is not None:
            return None
        user = self.add(email, status=UserStatus.PENDING, role=role, display_name=display_name)
        user = replace(user, password_hash=password_hash)
        self.users[user.user_id] = user
        return user

    async def get_by_email(self, email: str) -> User | None:
        return self.by_email(email)

    async def get_by_id(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    async def activate(self, user_id: str) -> User | None:
        user = self.users.get(user_id)
        if user is None:
            return None
        user = replace(user, status=UserStatus.ACTIVE, updated_at=self.tick())
        self.users[user_id] = user
        return user

    async def update_profile(
        self, user_id: str, changes: Mapping[ProfileField, str | None]
    ) -> User | None:
        user = self.users.get(user_id)
        if user is None:
            return None
        if ProfileField.DISPLAY_NAME in changes:
            user = replace(user, display_name=changes[ProfileField.DISPLAY_NAME] or "")
        if ProfileField.PHONE in changes:
            user = replace(user, phone=changes[ProfileField.PHONE])
        user = replace(user, updated_at=self.tick())
        self.users[user_id] = user
        return user

    async def set_password(self, email: str, password_hash: str) -> bool:
        user = self.by_email(email)
        if user is None:
            return False
        self.users[user.user_id] = replace(user, password_hash=password_hash)
        return True


class FakeConfirmCodes(ConfirmCodes):
    def __init__(self) -> None:
        self.codes: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def save(self, email: str, code: str, ttl_seconds: int) -> None:
        self.codes[email] = code
        self.ttls[email] = ttl_seconds

    async def get(self, email: str) -> str | None:
        return self.codes.get(email)

    async def delete(self, email: str) -> None:
        self.codes.pop(email, None)


class FakeSessions(Sessions):
    def __init__(self) -> None:
        self.users: dict[str, CurrentUser] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, token: str) -> CurrentUser | None:
        return self.users.get(token)

    async def save(self, token: str, user: CurrentUser, ttl_seconds: int) -> None:
        self.users[token] = user
        self.ttls[token] = ttl_seconds

    async def delete(self, token: str) -> None:
        self.users.pop(token, None)
