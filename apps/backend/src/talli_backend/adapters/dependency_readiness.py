"""Bounded operational probes; no business data, policy, or provider operations."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
import json
import time
from urllib.parse import urlsplit

import httpx
import psycopg
from psycopg import sql


PROBE_TIMEOUT_SECONDS = 2.0
TOTAL_TIMEOUT_SECONDS = 3.0
CACHE_SECONDS = 2.0
MAX_RESPONSE_BYTES = 16_384
ReadinessProbe = Callable[[], Awaitable[bool]]


class CachedReadiness:
    """One bounded in-flight probe per process; caller cancellation cannot fan out."""

    def __init__(self, probe: ReadinessProbe, *, deadline: float = TOTAL_TIMEOUT_SECONDS,
                 ttl: float = CACHE_SECONDS):
        self._probe = probe
        self._deadline = deadline
        self._ttl = ttl
        self._task: asyncio.Task[bool] | None = None
        self._expires = 0.0
        self._result = False

    async def _run(self) -> bool:
        try:
            async with asyncio.timeout(self._deadline):
                self._result = (await self._probe()) is True
        except Exception:
            self._result = False
        self._expires = time.monotonic() + self._ttl
        return self._result

    async def __call__(self) -> bool:
        if time.monotonic() < self._expires:
            return self._result
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        return await asyncio.shield(self._task)

    async def close(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


def _auth_origin(raw: str) -> str:
    parsed = urlsplit(raw)
    if (not raw or raw != raw.strip() or any(ord(c) < 33 for c in raw)
            or parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment
            or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})):
        raise ValueError("Invalid readiness configuration")
    return raw.rstrip("/")


async def probe_auth(origin: str, key: str) -> bool:
    """Settings is behind Supabase gateway key-auth; /health alone is insufficient."""
    try:
        origin = _auth_origin(origin)
        if not key or key != key.strip() or len(key) > 8192 or any(ord(c) < 33 for c in key):
            return False
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS), httpx.AsyncClient(
            timeout=PROBE_TIMEOUT_SECONDS, follow_redirects=False, trust_env=False,
        ) as client:
            async with client.stream("GET", origin + "/auth/v1/settings", headers={"apikey": key}) as response:
                if response.status_code != 200 or response.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                    return False
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        return False
                data = json.loads(body)
                return (isinstance(data, dict) and isinstance(data.get("external"), dict)
                        and isinstance(data["external"].get("email"), bool)
                        and isinstance(data.get("disable_signup"), bool))
    except Exception:
        return False


async def probe_database(dsn: str, roles: tuple[str, ...]) -> bool:
    """Authenticate the actual DSN and exercise SET ROLE grants in read-only work."""
    if not dsn or not roles:
        return False
    connection = None
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            connection = await psycopg.AsyncConnection.connect(
                dsn, connect_timeout=2, autocommit=True,
                options="-c statement_timeout=1000 -c lock_timeout=500 -c default_transaction_read_only=on",
            )
            async with connection.transaction():
                await connection.execute("set transaction read only")
                for role in roles:
                    await connection.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
                    cursor = await connection.execute("select 1")
                    if await cursor.fetchone() != (1,):
                        return False
            return True
    except Exception:
        return False
    finally:
        if connection is not None:
            # close() finishes the libpq connection synchronously before its first
            # suspension; cancellation must not leave an authenticated session.
            await connection.close()


def configured_readiness(environment: Mapping[str, str], database_roles: Mapping[str, tuple[str, ...]],
                         *, auth_required: bool) -> ReadinessProbe:
    """Snapshot configuration selected by HTTP composition, never DATABASE_URL."""
    grouped: dict[str, set[str]] = {}
    for setting, roles in database_roles.items():
        fallback = environment.get("TALLI_LEDGER_DATABASE_URL", "") if setting == "TALLI_BANKING_DATABASE_URL" else ""
        dsn = environment.get(setting, fallback)
        grouped.setdefault(dsn, set()).update(roles)
    databases = tuple((dsn, tuple(sorted(roles))) for dsn, roles in grouped.items())
    origin = environment.get("SUPABASE_URL", "")
    key = environment.get("SUPABASE_ANON_KEY", "")

    async def probe() -> bool:
        probes = [probe_database(dsn, roles) for dsn, roles in databases]
        if auth_required:
            probes.append(probe_auth(origin, key))
        if not probes:
            return False  # custom compositions must inject their own probe
        # TaskGroup cancels and drains every child at the overall deadline.
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(check) for check in probes]
        return all(task.result() for task in tasks)

    return probe
