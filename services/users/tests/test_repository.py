"""SQL репозитория против Postgres из compose (make up) во временной базе.

Без доступного Postgres тесты пропускаются: unit-тесты хэндлеров обходятся без него.
Адрес — env TEST_POSTGRES_DSN, по умолчанию Postgres из compose на localhost.
"""

import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
from stand_core.clients import Postgres
from stand_core.grpc import Role
from user_service.models import ProfileField, UserStatus
from user_service.passwords import verify_password
from user_service.repository import SEED_SELLER_EMAIL, SEED_SELLER_ID, UserRepository
from user_service.settings import UserSettings

ADMIN_DSN = os.environ.get("TEST_POSTGRES_DSN", "postgresql://stand:stand@localhost:5432/stand")
SEED_PASSWORD = "seed-password-under-test"


@pytest.fixture
async def postgres(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Postgres]:
    try:
        admin = await asyncpg.connect(ADMIN_DSN, timeout=2)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres is not available ({exc}); run make up")
    database = f"users_test_{uuid.uuid4().hex[:12]}"
    await admin.execute(f'CREATE DATABASE "{database}"')
    monkeypatch.setenv("POSTGRES_DSN", f"{ADMIN_DSN.rsplit('/', 1)[0]}/{database}")
    monkeypatch.setenv("SEED_SELLER_PASSWORD", SEED_PASSWORD)
    client = Postgres(UserSettings())
    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.close()


@pytest.fixture
async def repository(postgres: Postgres) -> UserRepository:
    repository = UserRepository(postgres, UserSettings())
    await repository.connect()
    return repository


async def test_seed_seller_is_active_with_password_from_env(repository: UserRepository) -> None:
    seller = await repository.get_by_email(SEED_SELLER_EMAIL)

    assert seller is not None
    assert seller.user_id == SEED_SELLER_ID
    assert (seller.role, seller.status) == (Role.SELLER, UserStatus.ACTIVE)
    assert verify_password(SEED_PASSWORD, seller.password_hash)


async def test_connect_again_keeps_seed_changes(
    repository: UserRepository, postgres: Postgres
) -> None:
    await repository.set_password(SEED_SELLER_EMAIL, "changed")

    await UserRepository(postgres, UserSettings()).connect()

    seller = await repository.get_by_id(SEED_SELLER_ID)
    assert seller is not None
    assert seller.password_hash == "changed"


async def test_create_activate_and_duplicate(repository: UserRepository) -> None:
    created = await repository.create_user("new@example.com", "hash", "Иван", Role.BUYER)
    duplicate = await repository.create_user("new@example.com", "hash2", "Пётр", Role.SELLER)
    assert created is not None
    activated = await repository.activate(created.user_id)

    assert created.status is UserStatus.PENDING
    assert created.phone is None
    assert duplicate is None
    assert activated is not None
    assert activated.status is UserStatus.ACTIVE
    assert activated.updated_at >= created.updated_at
    assert await repository.activate("missing") is None


async def test_update_profile_touches_only_given_fields(repository: UserRepository) -> None:
    user = await repository.create_user("new@example.com", "hash", "Иван", Role.BUYER)
    assert user is not None

    with_phone = await repository.update_profile(user.user_id, {ProfileField.PHONE: "+7999"})
    renamed = await repository.update_profile(user.user_id, {ProfileField.DISPLAY_NAME: "Пётр"})
    cleared = await repository.update_profile(user.user_id, {ProfileField.PHONE: None})
    unchanged = await repository.update_profile(user.user_id, {})

    assert with_phone is not None
    assert (with_phone.display_name, with_phone.phone) == ("Иван", "+7999")
    assert renamed is not None
    assert (renamed.display_name, renamed.phone) == ("Пётр", "+7999")
    assert cleared is not None
    assert cleared.phone is None
    assert unchanged == cleared
    assert await repository.update_profile("missing", {ProfileField.PHONE: None}) is None


async def test_set_password(repository: UserRepository) -> None:
    await repository.create_user("new@example.com", "hash", "Иван", Role.BUYER)

    assert await repository.set_password("new@example.com", "new-hash")
    assert not await repository.set_password("ghost@example.com", "new-hash")
    user = await repository.get_by_email("new@example.com")
    assert user is not None
    assert user.password_hash == "new-hash"
