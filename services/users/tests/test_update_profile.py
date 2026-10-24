from unittest.mock import Mock

import pytest
from google.protobuf.field_mask_pb2 import FieldMask
from stand_core.grpc import FieldViolation, InvalidArgument
from user_service.handlers.update_profile_u_u import update_profile
from user_service.models import User
from users.v1 import users_pb2

from .fakes import FakeRepository


def request(
    *paths: str, display_name: str = "", phone: str | None = None
) -> users_pb2.UpdateProfileRequest:
    profile = users_pb2.Profile(display_name=display_name)
    if phone is not None:
        profile.phone = phone
    return users_pb2.UpdateProfileRequest(profile=profile, update_mask=FieldMask(paths=paths))


async def test_updates_only_masked_fields(
    repository: FakeRepository, context: Mock, buyer: User
) -> None:
    # display_name задан в profile, но не в маске — не меняется
    response = await update_profile(
        request("phone", display_name="Другое имя", phone="+70000000000"), context, repository
    )

    assert response.user.phone == "+70000000000"
    assert response.user.display_name == "Покупатель"
    assert repository.users[buyer.user_id].phone == "+70000000000"


async def test_updates_display_name(repository: FakeRepository, context: Mock, buyer: User) -> None:
    response = await update_profile(
        request("display_name", display_name="  Иван  "), context, repository
    )

    assert response.user.display_name == "Иван"
    assert response.user.phone == "+79990001122"


async def test_phone_in_mask_without_value_clears_it(
    repository: FakeRepository, context: Mock, buyer: User
) -> None:
    response = await update_profile(request("phone"), context, repository)

    assert not response.user.HasField("phone")
    assert repository.users[buyer.user_id].phone is None


async def test_unknown_path_is_invalid_argument(
    repository: FakeRepository, context: Mock, buyer: User
) -> None:
    with pytest.raises(InvalidArgument) as info:
        await update_profile(
            request("display_name", "email", display_name="Иван"), context, repository
        )

    assert [v.field for v in info.value.field_violations] == ["update_mask.paths[1]"]
    assert repository.users[buyer.user_id].display_name == "Покупатель"


async def test_empty_mask_is_invalid_argument(
    repository: FakeRepository, context: Mock, buyer: User
) -> None:
    with pytest.raises(InvalidArgument) as info:
        await update_profile(request(display_name="Иван"), context, repository)

    assert [v.field for v in info.value.field_violations] == ["update_mask"]


async def test_values_are_validated(repository: FakeRepository, context: Mock, buyer: User) -> None:
    with pytest.raises(InvalidArgument) as info:
        await update_profile(
            request("display_name", "phone", display_name=" ", phone="call me"),
            context,
            repository,
        )

    assert info.value.field_violations == [
        FieldViolation("profile.display_name", "must not be empty"),
        FieldViolation("profile.phone", "must be 5-15 digits with an optional leading +"),
    ]
