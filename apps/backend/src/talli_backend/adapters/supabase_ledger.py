"""Verified-actor, restricted PostgreSQL adapter for the ledger capability."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import psycopg
from psycopg.rows import dict_row

from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.application.ledger_workflow import (
    LedgerApplication,
    LedgerSessionFactory,
    NewYearStartCommand,
)
from talli_backend.modules.ledger.public import (
    LedgerCommand,
    LedgerCursor,
    LedgerEntryId,
    LedgerEntryKind,
    LedgerEntryPage,
    LedgerEntryView,
    LedgerError,
    LedgerLine,
    LedgerPersistence,
    LedgerRiskCode,
    LedgerRiskFlag,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    LedgerPage,
    LockPeriodCommand,
    PeriodLock,
    PeriodLockId,
    PeriodLockPage,
    PostedLedgerEntry,
    ledger_persistence_adapter,
)
from talli_backend.modules.shareholder_register_filing.public import (
    OpeningSnapshotId,
    RecordOpeningSnapshotCommand,
)
from talli_backend.modules.ledger.service import LedgerService
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IncomeYear,
    Money,
    Timestamp,
    UserId,
)


@dataclass(frozen=True)
class LedgerSupabaseConfiguration:
    url: str
    anon_key: str
    database_url: str = ""


@dataclass(frozen=True)
class _VerifiedActor:
    actor_id: ActorId
    claims_json: str


def _validated_origin(raw: str) -> str:
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        _ = parsed.port
        hostname = parsed.hostname
    except (ValueError, UnicodeError):
        raise ValueError("Supabase origin is invalid") from None
    is_loopback = hostname == "localhost"
    if hostname is not None and not is_loopback:
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = False
    if (
        parsed.scheme not in {"http", "https"}
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (parsed.scheme == "http" and not is_loopback)
    ):
        raise ValueError("Supabase origin is unsafe")
    return f"{parsed.scheme}://{parsed.netloc}"


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def _timestamp(value: object) -> Timestamp:
    if isinstance(value, datetime):
        return Timestamp(value)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return Timestamp(parsed)
    raise ValueError("ledger timestamp is invalid")


def _actor(value: object) -> ActorId:
    return ActorId(kind=ActorKind.USER, subject=UserId(str(value)))


def _money(value: object, currency: object = "NOK") -> Money:
    if str(currency) != "NOK":
        raise ValueError("ledger currency is invalid")
    if isinstance(value, Decimal):
        return Money.nok(value)
    return Money.nok(str(value))


def _line_payload(line: LedgerLine) -> dict[str, str]:
    return {
        "account": line.account,
        "description": line.description,
        "debit": format(line.debit.amount, "f"),
        "credit": format(line.credit.amount, "f"),
        "currency": line.debit.currency.value,
    }


def _risk_payload(flag: LedgerRiskFlag) -> dict[str, str]:
    return {"code": flag.code.value, "account": flag.account}


def _map_database_error(message: str) -> LedgerError:
    definitions = (
        ("ledger_not_found", LedgerError.not_found()),
        ("ledger_forbidden", LedgerError.forbidden()),
        (
            "ledger_period_locked",
            LedgerError.precondition_failed("LEDGER_PERIOD_LOCKED"),
        ),
        (
            "ledger_company_year_not_admitted",
            LedgerError.precondition_failed("LEDGER_COMPANY_YEAR_NOT_ADMITTED"),
        ),
        (
            "ledger_opening_already_exists",
            LedgerError.conflict("LEDGER_OPENING_ALREADY_EXISTS"),
        ),
        (
            "ledger_idempotency_key_reused",
            LedgerError.conflict("LEDGER_IDEMPOTENCY_KEY_REUSED"),
        ),
        (
            "ledger_idempotency_in_progress",
            LedgerError.conflict("LEDGER_IDEMPOTENCY_IN_PROGRESS"),
        ),
        (
            "ledger_invalid_cursor",
            LedgerError.invalid_input("LEDGER_INVALID_CURSOR"),
        ),
        ("ledger_invalid_input", LedgerError.invalid_input("LEDGER_INVALID_INPUT")),
    )
    for marker, mapped in definitions:
        if marker in message:
            return mapped
    return LedgerError.unavailable()


class SupabaseLedgerAdapter:
    """Authenticate one bearer and return a request-bound RLS persistence session."""

    def __init__(self, configuration: LedgerSupabaseConfiguration) -> None:
        self._configuration = configuration
        self._origin = _validated_origin(configuration.url)
        self._anon_key = configuration.anon_key
        self._opener = build_opener(_RejectRedirects)

    @classmethod
    def from_environment(cls) -> SupabaseLedgerAdapter:
        return cls(
            LedgerSupabaseConfiguration(
                url=os.environ.get("SUPABASE_URL", ""),
                anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
                database_url=os.environ.get("TALLI_LEDGER_DATABASE_URL", ""),
            )
        )

    def _unavailable(self) -> LedgerError:
        return LedgerError.unavailable()

    async def _auth_user(self, access_token: str) -> Mapping[str, object]:
        if not self._origin or not self._anon_key or not access_token:
            raise self._unavailable()

        def send() -> Mapping[str, object]:
            request = Request(
                f"{self._origin}/auth/v1/user",
                method="GET",
                headers={
                    "apikey": self._anon_key,
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            try:
                with self._opener.open(request, timeout=5) as response:
                    if response.status != 200:
                        raise LedgerAuthenticationError
                    body = response.read(65_537)
                    if len(body) > 65_536:
                        raise self._unavailable()
                    decoded = json.loads(body.decode("utf-8"))
            except HTTPError as error:
                if error.code in {401, 403}:
                    raise LedgerAuthenticationError from None
                raise self._unavailable() from None
            except (URLError, TimeoutError, json.JSONDecodeError):
                raise self._unavailable() from None
            if not isinstance(decoded, Mapping):
                raise LedgerAuthenticationError
            return decoded

        return await asyncio.to_thread(send)

    async def _verified_actor(self, access_token: str) -> _VerifiedActor:
        identity = await self._auth_user(access_token)
        identity_id = identity.get("id")
        identity_email = identity.get("email")
        if not isinstance(identity_id, str) or not isinstance(identity_email, str):
            raise LedgerAuthenticationError
        try:
            payload = access_token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload))
        except (IndexError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            raise LedgerAuthenticationError from None
        if not isinstance(decoded, Mapping) or decoded.get("sub") != identity_id:
            raise LedgerAuthenticationError
        claims: dict[str, object] = {
            "sub": identity_id,
            "email": identity_email.strip().lower(),
            "role": "authenticated",
            "aal": decoded.get("aal") if decoded.get("aal") in {"aal1", "aal2"} else "aal1",
        }
        if isinstance(decoded.get("amr"), list):
            claims["amr"] = decoded["amr"]
        return _VerifiedActor(
            actor_id=_actor(identity_id),
            claims_json=json.dumps(claims, separators=(",", ":")),
        )

    async def session(self, access_token: str) -> SupabaseLedgerSession:
        verified = await self._verified_actor(access_token)
        return SupabaseLedgerSession(self._configuration.database_url, verified)


@ledger_persistence_adapter(LedgerPersistence)
class SupabaseLedgerSession:
    def __init__(self, database_url: str, verified: _VerifiedActor) -> None:
        self._database_url = database_url
        self._verified = verified

    @property
    def actor_id(self) -> ActorId:
        return self._verified.actor_id

    def _unavailable(self) -> LedgerError:
        return LedgerError.unavailable()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[SupabaseLedgerWorkflowTransaction]:
        if not self._database_url:
            raise self._unavailable()
        try:
            async with await psycopg.AsyncConnection.connect(
                self._database_url,
                connect_timeout=5,
                row_factory=dict_row,
            ) as connection:
                async with connection.transaction():
                    await connection.execute("set local role ledger_workflow_executor")
                    await connection.execute(
                        "select pg_catalog.set_config('talli.verified_actor_id', %s, true)",
                        (str(self.actor_id.subject),),
                    )
                    await connection.execute(
                        "select pg_catalog.set_config('talli.verified_actor_claims', %s, true)",
                        (self._verified.claims_json,),
                    )
                    yield SupabaseLedgerWorkflowTransaction(
                        self._database_url,
                        self._verified,
                        connection,
                    )
        except LedgerError:
            raise
        except psycopg.OperationalError:
            raise self._unavailable() from None
        except psycopg.DatabaseError as error:
            raise _map_database_error(str(error)) from None

    async def _database_rows(
        self,
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> list[Mapping[str, object]]:
        if not self._database_url:
            raise self._unavailable()

        def execute() -> list[Mapping[str, object]]:
            try:
                with psycopg.connect(
                    self._database_url,
                    connect_timeout=5,
                    row_factory=dict_row,
                ) as connection, connection.transaction():
                    connection.execute("set local role ledger_executor")
                    connection.execute(
                        "select pg_catalog.set_config('talli.verified_actor_id', %s, true)",
                        (str(self.actor_id.subject),),
                    )
                    connection.execute(
                        "select pg_catalog.set_config('talli.verified_actor_claims', %s, true)",
                        (self._verified.claims_json,),
                    )
                    return list(connection.execute(query, parameters).fetchall())
            except psycopg.OperationalError:
                raise self._unavailable() from None
            except psycopg.DatabaseError as error:
                raise _map_database_error(str(error)) from None

        return await asyncio.to_thread(execute)

    async def _one_idempotent_row(
        self,
        query: str,
        parameters: tuple[object, ...],
    ) -> Mapping[str, object]:
        for attempt in range(2):
            try:
                rows = await self._database_rows(query, parameters)
            except LedgerError as error:
                if error.code != "LEDGER_DEPENDENCY_UNAVAILABLE" or attempt == 1:
                    raise
                continue
            if len(rows) == 1:
                return rows[0]
            if attempt == 1:
                break
        raise self._unavailable()

    async def post_entry(
        self,
        command: LedgerCommand,
        *,
        entry_kind: LedgerEntryKind,
        memo: str,
        lines: tuple[LedgerLine, ...],
        risk_flags: tuple[LedgerRiskFlag, ...],
        warning_accepted: bool,
        source_capability: LedgerSourceCapability,
        source_record_id: LedgerSourceRecordId,
    ) -> PostedLedgerEntry:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        lines_payload = [_line_payload(line) for line in lines]
        risks_payload = [_risk_payload(flag) for flag in risk_flags]
        row = await self._one_idempotent_row(
            """
            select * from ledger.post_entry(
              %s::text, %s::uuid, %s::integer, %s::text, %s::text,
              %s::jsonb, %s::jsonb, %s::boolean, %s::text, %s::text, %s::text, %s::text
            )
            """,
            (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                entry_kind.value,
                memo,
                json.dumps(lines_payload, separators=(",", ":")),
                json.dumps(risks_payload, separators=(",", ":")),
                warning_accepted,
                source_capability.value,
                str(source_record_id),
                str(command.correlation_id),
                str(command.actor_id.subject),
            ),
        )
        return PostedLedgerEntry(
            entry_id=LedgerEntryId(str(row["ledger_entry_id"])),
            company_id=CompanyId(str(row["company_id"])),
            income_year=IncomeYear(int(row["income_year"])),
            entry_kind=LedgerEntryKind(str(row["entry_kind"])),
            posted_at=_timestamp(row["posted_at"]),
            replayed=bool(row["replayed"]),
        )

    async def lock_period(self, command: LockPeriodCommand) -> PeriodLock:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        row = await self._one_idempotent_row(
            """
            select * from ledger.lock_period(
              %s::text, %s::uuid, %s::integer, %s::text, %s::text, %s::text
            )
            """,
            (
                str(command.idempotency_key),
                str(command.company_id),
                int(command.income_year),
                command.reason.strip(),
                str(command.correlation_id),
                str(command.actor_id.subject),
            ),
        )
        return PeriodLock(
            period_lock_id=PeriodLockId(str(row["period_lock_id"])),
            company_id=CompanyId(str(row["company_id"])),
            income_year=IncomeYear(int(row["income_year"])),
            reason=str(row["reason"]),
            locked_by=_actor(row["locked_by"]),
            locked_at=_timestamp(row["locked_at"]),
            replayed=bool(row["replayed"]),
        )

    async def list_entries(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> LedgerEntryPage:
        if actor_id != self.actor_id:
            raise LedgerError.forbidden()
        _ = correlation_id
        rows = await self._database_rows(
            "select * from ledger.list_entries(%s::uuid[], %s::text, %s::integer, %s::text)",
            (
                [str(company_id) for company_id in company_ids],
                str(cursor) if cursor is not None else None,
                limit,
                str(actor_id.subject),
            ),
        )
        if len(rows) != 1:
            raise self._unavailable()
        items_payload = rows[0].get("items")
        if not isinstance(items_payload, list):
            raise self._unavailable()
        try:
            entries = tuple(self._entry_view(item) for item in items_payload)
        except (KeyError, TypeError, ValueError):
            raise self._unavailable() from None
        return LedgerEntryPage(
            items=entries,
            page=LedgerPage(
                next_cursor=(
                    LedgerCursor(str(rows[0]["next_cursor"]))
                    if rows[0].get("next_cursor") is not None
                    else None
                ),
                has_more=bool(rows[0].get("has_more")),
            ),
        )

    async def list_period_locks(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> PeriodLockPage:
        if actor_id != self.actor_id:
            raise LedgerError.forbidden()
        _ = correlation_id
        rows = await self._database_rows(
            "select * from ledger.list_period_locks(%s::uuid[], %s::text, %s::integer, %s::text)",
            (
                [str(company_id) for company_id in company_ids],
                str(cursor) if cursor is not None else None,
                limit,
                str(actor_id.subject),
            ),
        )
        if len(rows) != 1 or not isinstance(rows[0].get("items"), list):
            raise self._unavailable()
        try:
            items = tuple(self._period_lock(item) for item in rows[0]["items"])
        except (KeyError, TypeError, ValueError):
            raise self._unavailable() from None
        return PeriodLockPage(
            items=items,
            page=LedgerPage(
                next_cursor=(
                    LedgerCursor(str(rows[0]["next_cursor"]))
                    if rows[0].get("next_cursor") is not None
                    else None
                ),
                has_more=bool(rows[0].get("has_more")),
            ),
        )

    def _entry_view(self, value: object) -> LedgerEntryView:
        if not isinstance(value, Mapping):
            raise ValueError("invalid entry")
        raw_lines = value["lines"]
        raw_risks = value.get("riskFlags", [])
        if not isinstance(raw_lines, list) or not isinstance(raw_risks, list):
            raise ValueError("invalid entry payload")
        lines = tuple(
            LedgerLine(
                account=str(line["account"]),
                description=str(line["description"]),
                debit=_money(line["debit"], line.get("currency", "NOK")),
                credit=_money(line["credit"], line.get("currency", "NOK")),
            )
            for line in raw_lines
            if isinstance(line, Mapping)
        )
        risks = tuple(
            LedgerRiskFlag(
                code=LedgerRiskCode(str(flag["code"])),
                account=str(flag["account"]),
            )
            for flag in raw_risks
            if isinstance(flag, Mapping)
        )
        warning_actor = value.get("warningAcceptedBy")
        warning_at = value.get("warningAcceptedAt")
        return LedgerEntryView(
            entry_id=LedgerEntryId(str(value["entryId"])),
            company_id=CompanyId(str(value["companyId"])),
            income_year=IncomeYear(int(value["incomeYear"])),
            entry_kind=LedgerEntryKind(str(value["entryKind"])),
            memo=str(value["memo"]),
            lines=lines,
            risk_flags=risks,
            warning_accepted_by=_actor(warning_actor) if warning_actor else None,
            warning_accepted_at=_timestamp(warning_at) if warning_at else None,
            posted_by=_actor(value["postedBy"]),
            posted_at=_timestamp(value["postedAt"]),
        )

    def _period_lock(self, value: object) -> PeriodLock:
        if not isinstance(value, Mapping):
            raise ValueError("invalid period lock")
        return PeriodLock(
            period_lock_id=PeriodLockId(str(value["periodLockId"])),
            company_id=CompanyId(str(value["companyId"])),
            income_year=IncomeYear(int(value["incomeYear"])),
            reason=str(value["reason"]),
            locked_by=_actor(value["lockedBy"]),
            locked_at=_timestamp(value["lockedAt"]),
            replayed=False,
        )


class SupabaseLedgerWorkflowTransaction(SupabaseLedgerSession):
    """Ledger and frozen-facade operations bound to one PostgreSQL transaction."""

    def __init__(
        self,
        database_url: str,
        verified: _VerifiedActor,
        connection: psycopg.AsyncConnection[Mapping[str, object]],
    ) -> None:
        super().__init__(database_url, verified)
        self._connection = connection

    async def _database_rows(
        self,
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> list[Mapping[str, object]]:
        try:
            cursor = await self._connection.execute(query, parameters)
            return list(await cursor.fetchall())
        except psycopg.OperationalError:
            raise self._unavailable() from None
        except psycopg.DatabaseError as error:
            raise _map_database_error(str(error)) from None

    async def _one_idempotent_row(
        self,
        query: str,
        parameters: tuple[object, ...],
    ) -> Mapping[str, object]:
        rows = await self._database_rows(query, parameters)
        if len(rows) != 1:
            raise self._unavailable()
        return rows[0]

    def _new_year_command(self, command: object) -> NewYearStartCommand:
        if not isinstance(command, NewYearStartCommand):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        return command

    async def claim_workflow(
        self,
        *,
        operation_name: str,
        command: object,
        request: dict[str, object],
    ) -> dict[str, object] | None:
        typed = self._new_year_command(command)
        row = await self._one_idempotent_row(
            """
            select backend_system.claim_ledger_workflow_v1(
              %s::text, %s::text, %s::uuid, %s::jsonb, %s::text
            ) as result
            """,
            (
                operation_name,
                str(typed.idempotency_key),
                str(typed.company_id),
                json.dumps(request, separators=(",", ":")),
                str(typed.actor_id.subject),
            ),
        )
        result = row.get("result")
        if result is None:
            return None
        if not isinstance(result, Mapping):
            raise self._unavailable()
        return dict(result)

    async def record_legacy_opening_snapshot(
        self,
        command: RecordOpeningSnapshotCommand,
        *,
        ledger_bank_balance: Money,
    ) -> OpeningSnapshotId:
        if command.actor_id != self.actor_id:
            raise LedgerError.forbidden()
        typed = command
        shareholders = [
            {
                "name": shareholder.name,
                "shareholderKind": shareholder.shareholder_kind,
                "nationalId": shareholder.national_id,
                "orgNumber": shareholder.org_number,
                "shareCount": shareholder.share_count,
            }
            for shareholder in typed.shareholders
        ]
        row = await self._one_idempotent_row(
            """
            select backend_system.record_opening_snapshot_legacy_v1(
              %s::uuid, %s::integer, %s::numeric, %s::numeric,
              %s::integer, %s::numeric, %s::jsonb, %s::text
            ) as setup_id
            """,
            (
                str(typed.company_id),
                int(typed.income_year),
                ledger_bank_balance.amount,
                typed.share_capital.amount,
                typed.share_count,
                typed.nominal_value.amount,
                json.dumps(shareholders, separators=(",", ":")),
                str(typed.actor_id.subject),
            ),
        )
        return OpeningSnapshotId(str(row["setup_id"]))

    async def complete_workflow(
        self,
        *,
        operation_name: str,
        command: object,
        result: dict[str, object],
    ) -> None:
        typed = self._new_year_command(command)
        request = {
            "companyId": str(typed.company_id),
            "incomeYear": int(typed.income_year),
            "bankBalance": format(typed.bank_balance.amount, "f"),
            "shareCapital": format(typed.share_capital.amount, "f"),
            "shareCount": typed.share_count,
            "nominalValue": format(typed.nominal_value.amount, "f"),
            "shareholders": [
                {
                    "name": shareholder.name,
                    "shareholderKind": shareholder.shareholder_kind,
                    "nationalId": shareholder.national_id,
                    "orgNumber": shareholder.org_number,
                    "shareCount": shareholder.share_count,
                }
                for shareholder in typed.shareholders
            ],
        }
        await self._one_idempotent_row(
            """
            select backend_system.complete_ledger_workflow_v1(
              %s::text, %s::text, %s::uuid, %s::jsonb, %s::jsonb, %s::text
            ) as completed
            """,
            (
                operation_name,
                str(typed.idempotency_key),
                str(typed.company_id),
                json.dumps(request, separators=(",", ":")),
                json.dumps(result, separators=(",", ":")),
                str(typed.actor_id.subject),
            ),
        )


def compose_ledger_application(
    sessions: LedgerSessionFactory | None = None,
) -> LedgerApplication:
    """Bind the private ledger implementation outside the FastAPI composition root."""

    return LedgerApplication(
        sessions or SupabaseLedgerAdapter.from_environment(),
        LedgerService,
    )
