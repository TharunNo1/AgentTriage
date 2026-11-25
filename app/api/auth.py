import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.settings import Settings
from app.db.repositories import ApiClientRepository

Scope = Literal["ingest", "operator"]
API_KEY_PREFIX = "atk_"


@dataclass(frozen=True, slots=True)
class Principal:
    name: str
    scopes: frozenset[str]


def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def sign_body(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


async def authenticate(
    *,
    authorization: str | None,
    hmac_client: str | None,
    hmac_timestamp: str | None,
    hmac_signature: str | None,
    body: bytes,
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> Principal:
    """Bearer API key (hashed in DB) or HMAC-SHA256 body signature (secret from settings, ingest scope only)."""
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise UnauthorizedError("Malformed Authorization header")
        async with sessionmaker() as session:
            client = await ApiClientRepository(session).get_active_by_key_hash(hash_api_key(token))
        if client is None:
            raise UnauthorizedError("Invalid API key")
        return Principal(client.name, frozenset(client.scopes))

    if hmac_client and hmac_timestamp and hmac_signature:
        secret = settings.webhook_hmac_secrets.get(hmac_client)
        if secret is None:
            raise UnauthorizedError("Unknown HMAC client")
        try:
            skew = abs(time.time() - int(hmac_timestamp))
        except ValueError as exc:
            raise UnauthorizedError("Invalid signature timestamp") from exc
        if skew > settings.hmac_max_skew_seconds:
            raise UnauthorizedError("Signature timestamp outside allowed window")
        if not hmac.compare_digest(sign_body(secret.get_secret_value(), hmac_timestamp, body), hmac_signature):
            raise UnauthorizedError("Invalid signature")
        return Principal(hmac_client, frozenset({"ingest"}))

    raise UnauthorizedError("Missing credentials")


def require_scope(principal: Principal, scope: Scope) -> None:
    if scope not in principal.scopes:
        raise ForbiddenError(f"API client lacks the '{scope}' scope")
