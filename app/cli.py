import argparse
import asyncio

from app.api.auth import generate_api_key, hash_api_key
from app.core.settings import get_settings
from app.db.models import ApiClient
from app.db.repositories import ApiClientRepository
from app.db.session import create_engine, create_sessionmaker, transaction

VALID_SCOPES = {"ingest", "operator"}


async def _create(name: str, scopes: list[str]) -> None:
    engine = create_engine(get_settings())
    try:
        async with transaction(create_sessionmaker(engine)) as session:
            repo = ApiClientRepository(session)
            if await repo.get_by_name(name):
                raise SystemExit(f"API client '{name}' already exists")
            key = generate_api_key()
            repo.add(ApiClient(name=name, key_hash=hash_api_key(key), scopes=scopes, active=True))
        print(f"Created API client '{name}' with scopes {scopes}. Store this key now; it is not shown again:\n{key}")
    finally:
        await engine.dispose()


async def _set_active(name: str, active: bool) -> None:
    engine = create_engine(get_settings())
    try:
        async with transaction(create_sessionmaker(engine)) as session:
            client = await ApiClientRepository(session).get_by_name(name)
            if client is None:
                raise SystemExit(f"API client '{name}' not found")
            client.active = active
        print(f"API client '{name}' {'activated' if active else 'revoked'}")
    finally:
        await engine.dispose()


async def _list() -> None:
    engine = create_engine(get_settings())
    try:
        async with create_sessionmaker(engine)() as session:
            for c in await ApiClientRepository(session).all():
                print(f"{c.name}\tscopes={','.join(c.scopes)}\tactive={c.active}\tcreated={c.created_at:%Y-%m-%d}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-triage")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-api-key", help="Create an API client and print its key once")
    create.add_argument("--name", required=True)
    create.add_argument("--scopes", default="ingest", help="Comma-separated: ingest,operator")
    revoke = sub.add_parser("revoke-api-key")
    revoke.add_argument("--name", required=True)
    sub.add_parser("list-api-keys")
    args = parser.parse_args()

    if args.command == "create-api-key":
        scopes = sorted({s.strip() for s in args.scopes.split(",") if s.strip()})
        if not scopes or not set(scopes) <= VALID_SCOPES:
            parser.error(f"scopes must be a subset of {sorted(VALID_SCOPES)}")
        asyncio.run(_create(args.name, scopes))
    elif args.command == "revoke-api-key":
        asyncio.run(_set_active(args.name, False))
    else:
        asyncio.run(_list())


if __name__ == "__main__":
    main()
