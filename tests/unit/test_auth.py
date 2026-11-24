import time
from typing import Any

import pytest

from app.api.auth import Principal, authenticate, generate_api_key, hash_api_key, require_scope, sign_body
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.settings import Settings

SETTINGS = Settings(
    database_url="postgresql+asyncpg://u:p@localhost:5432/db",  # type: ignore[arg-type]
    webhook_hmac_secrets={"alertmanager": "s3cret"},  # type: ignore[dict-item]
)
BODY = b'{"status":"firing"}'


async def _auth(client: str | None, ts: str | None, sig: str | None, body: bytes = BODY) -> Principal:
    sessionmaker: Any = None  # HMAC path never touches the database
    return await authenticate(
        authorization=None,
        hmac_client=client,
        hmac_timestamp=ts,
        hmac_signature=sig,
        body=body,
        settings=SETTINGS,
        sessionmaker=sessionmaker,
    )


async def test_valid_hmac_grants_ingest_scope_only() -> None:
    ts = str(int(time.time()))
    principal = await _auth("alertmanager", ts, sign_body("s3cret", ts, BODY))
    assert principal == Principal("alertmanager", frozenset({"ingest"}))


@pytest.mark.parametrize(
    ("client", "ts_offset", "secret", "body"),
    [
        ("unknown", 0, "s3cret", BODY),
        ("alertmanager", 0, "wrong", BODY),
        ("alertmanager", 0, "s3cret", b"tampered"),
        ("alertmanager", -3600, "s3cret", BODY),
    ],
)
async def test_invalid_hmac_is_rejected(client: str, ts_offset: int, secret: str, body: bytes) -> None:
    ts = str(int(time.time()) + ts_offset)
    with pytest.raises(UnauthorizedError):
        await _auth(client, ts, sign_body(secret, ts, BODY), body=body)


async def test_missing_credentials() -> None:
    with pytest.raises(UnauthorizedError):
        await _auth(None, None, None)


async def test_non_numeric_timestamp() -> None:
    with pytest.raises(UnauthorizedError):
        await _auth("alertmanager", "yesterday", "sha256=00")


def test_api_keys_are_random_and_hashed() -> None:
    a, b = generate_api_key(), generate_api_key()
    assert a != b and a.startswith("atk_")
    assert hash_api_key(a) != a and len(hash_api_key(a)) == 64


def test_require_scope() -> None:
    require_scope(Principal("x", frozenset({"operator"})), "operator")
    with pytest.raises(ForbiddenError):
        require_scope(Principal("x", frozenset({"ingest"})), "operator")
