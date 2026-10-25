from stand_core.clients.sessions import decode_session, encode_session, session_key
from stand_core.grpc.context import CurrentUser, Role
from stand_core.grpc.interceptors.auth import bearer_token


def test_session_round_trip() -> None:
    user = CurrentUser("u1", Role.SELLER)

    assert decode_session(encode_session(user)) == user
    assert session_key("abc") == "session:abc"


def test_broken_session_is_none() -> None:
    assert decode_session("not json") is None
    assert decode_session('{"user_id": "u1", "role": "ADMIN"}') is None
    assert decode_session('{"role": "BUYER"}') is None
    assert decode_session("[]") is None


def test_bearer_token() -> None:
    assert bearer_token("Bearer abc") == "abc"
    assert bearer_token("bearer  abc ") == "abc"
    assert bearer_token("Basic abc") is None
    assert bearer_token("Bearer ") is None
    assert bearer_token(None) is None
