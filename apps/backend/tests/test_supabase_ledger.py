from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from talli_backend.adapters.supabase_ledger import (
    LedgerSupabaseConfiguration,
    SupabaseLedgerAdapter,
    SupabaseLedgerSession,
    _VerifiedActor,
    _map_database_error,
)
from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.modules.ledger.public import (
    LedgerEntryKind,
    LedgerError,
    LedgerLine,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    PostManualJournalCommand,
)
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    Money,
    UserId,
)


ACTOR_ID = ActorId(
    kind=ActorKind.USER,
    subject=UserId("20000000-0000-0000-0000-000000000002"),
)
OTHER_ACTOR = ActorId(
    kind=ActorKind.USER,
    subject=UserId("20000000-0000-0000-0000-000000000099"),
)


def token(subject: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": subject, "aal": "aal2"}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


def command(actor_id: ActorId = ACTOR_ID) -> PostManualJournalCommand:
    return PostManualJournalCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=actor_id,
        correlation_id=CorrelationId("ledger-adapter-test"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000003"),
        income_year=IncomeYear(2026),
        memo="Manual entry",
        lines=(
            LedgerLine("7795", "Cost", Money.nok("100"), Money.nok("0")),
            LedgerLine("1920", "Bank", Money.nok("0"), Money.nok("100")),
        ),
        warning_accepted=False,
    )


def bound_session() -> SupabaseLedgerSession:
    return SupabaseLedgerSession(
        "postgresql://unused",
        _VerifiedActor(
            actor_id=ACTOR_ID,
            claims_json=(
                '{"sub":"20000000-0000-0000-0000-000000000002",'
                '"role":"authenticated","aal":"aal2"}'
            ),
        ),
    )


def test_session_binds_auth_user_to_matching_bearer_subject() -> None:
    adapter = SupabaseLedgerAdapter(
        LedgerSupabaseConfiguration(
            url="https://project.supabase.co",
            anon_key="anon-test-key",
            database_url="postgresql://unused",
        )
    )

    async def auth_user(_token: str) -> dict[str, str]:
        return {"id": str(ACTOR_ID.subject), "email": " Owner@Example.Test "}

    adapter._auth_user = auth_user  # type: ignore[method-assign]
    session = asyncio.run(adapter.session(token(str(ACTOR_ID.subject))))

    assert session.actor_id == ACTOR_ID
    assert json.loads(session._verified.claims_json) == {
        "sub": str(ACTOR_ID.subject),
        "email": "owner@example.test",
        "role": "authenticated",
        "aal": "aal2",
    }

    with pytest.raises(LedgerAuthenticationError):
        asyncio.run(adapter.session(token(str(OTHER_ACTOR.subject))))


@pytest.mark.parametrize(
    "unsafe",
    [
        "http://project.supabase.co",
        "https://user:pass@project.supabase.co",
        "https://project.supabase.co/path",
        "file:///tmp/socket",
    ],
)
def test_adapter_rejects_unsafe_auth_origins(unsafe: str) -> None:
    with pytest.raises(ValueError):
        SupabaseLedgerAdapter(
            LedgerSupabaseConfiguration(url=unsafe, anon_key="anon-test-key")
        )


def test_bound_session_rejects_a_forged_command_actor_before_database_io() -> None:
    session = bound_session()

    async def forbidden_database(*_args: object, **_kwargs: object) -> list[object]:
        raise AssertionError("database must not be called")

    session._database_rows = forbidden_database  # type: ignore[method-assign]
    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            session.post_entry(
                command(OTHER_ACTOR),
                entry_kind=LedgerEntryKind.MANUAL_JOURNAL,
                memo="Manual entry",
                lines=command(OTHER_ACTOR).lines,
                risk_flags=(),
                warning_accepted=False,
                source_capability=LedgerSourceCapability.LEDGER,
                source_record_id=LedgerSourceRecordId("source-1"),
            )
        )
    assert failure.value.code == "LEDGER_FORBIDDEN"


def test_unknown_post_outcome_retries_the_identical_idempotent_rpc_once() -> None:
    session = bound_session()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        if len(calls) == 1:
            raise LedgerError.unavailable()
        return [{
            "ledger_entry_id": "40000000-0000-0000-0000-000000000004",
            "company_id": "10000000-0000-0000-0000-000000000001",
            "income_year": 2026,
            "entry_kind": "MANUAL_JOURNAL",
            "posted_at": datetime(2026, 8, 27, 10, tzinfo=UTC),
            "replayed": True,
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    posted = asyncio.run(
        session.post_entry(
            command(),
            entry_kind=LedgerEntryKind.MANUAL_JOURNAL,
            memo="Manual entry",
            lines=command().lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.LEDGER,
            source_record_id=LedgerSourceRecordId("source-1"),
        )
    )

    assert posted.replayed is True
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert "ledger.post_entry" in calls[0][0]


def test_adapter_never_uses_a_service_role_business_path() -> None:
    source = Path(__file__).parents[1].joinpath(
        "src/talli_backend/adapters/supabase_ledger.py"
    ).read_text(encoding="utf-8")
    assert "service_role" not in source
    assert "set local role ledger_executor" in source
    assert "talli.verified_actor_id" in source
    assert "talli.verified_actor_claims" in source
    assert "ledger_invalid_cursor" in source
    assert 'LedgerError.invalid_input("LEDGER_INVALID_CURSOR")' in source


@pytest.mark.parametrize(
    ("marker", "code"),
    [
        ("ledger_company_year_not_admitted", "LEDGER_COMPANY_YEAR_NOT_ADMITTED"),
        ("ledger_opening_already_exists", "LEDGER_OPENING_ALREADY_EXISTS"),
    ],
)
def test_declared_database_outcomes_keep_their_closed_contract(
    marker: str, code: str
) -> None:
    assert _map_database_error(marker).code == code


def test_entry_projection_keeps_the_exact_warning_acceptance_timestamp() -> None:
    payload = {
        "entryId": "40000000-0000-0000-0000-000000000004",
        "companyId": "10000000-0000-0000-0000-000000000001",
        "incomeYear": 2026,
        "entryKind": "MANUAL_JOURNAL",
        "sourceCapability": "LEDGER",
        "sourceRecordId": "manual:test-projection",
        "createdAt": "2026-08-27T09:59:57Z",
        "memo": "Manual entry",
        "lines": [
            {
                "account": "7795",
                "description": "Cost",
                "debit": "100.00",
                "credit": "0.00",
                "currency": "NOK",
            },
            {
                "account": "1920",
                "description": "Bank",
                "debit": "0.00",
                "credit": "100.00",
                "currency": "NOK",
            },
        ],
        "riskFlags": [],
        "warningAcceptedBy": str(ACTOR_ID.subject),
        "warningAcceptedAt": "2026-08-27T09:59:58Z",
        "postedBy": str(ACTOR_ID.subject),
        "postedAt": "2026-08-27T10:00:00Z",
    }
    projected = bound_session()._entry_view(payload)

    assert projected.warning_accepted_at is not None
    assert projected.warning_accepted_at.value == datetime(
        2026, 8, 27, 9, 59, 58, tzinfo=UTC
    )
    assert projected.source_capability is LedgerSourceCapability.LEDGER
    assert projected.source_record_id == LedgerSourceRecordId(
        "manual:test-projection"
    )
    assert projected.created_at is not None
    assert projected.created_at.value == datetime(
        2026, 8, 27, 9, 59, 57, tzinfo=UTC
    )

    legacy_payload = dict(payload)
    legacy_payload.pop("sourceCapability")
    legacy_payload.pop("sourceRecordId")
    legacy_payload.pop("createdAt")
    legacy = bound_session()._entry_view(legacy_payload)
    assert legacy.source_capability is None
    assert legacy.source_record_id is None
    assert legacy.created_at is None

    partial_payload = dict(legacy_payload)
    partial_payload["sourceCapability"] = "LEDGER"
    with pytest.raises(ValueError, match="source identity"):
        bound_session()._entry_view(partial_payload)

    partial_payload = dict(payload)
    partial_payload.pop("createdAt")
    with pytest.raises(ValueError, match="source identity"):
        bound_session()._entry_view(partial_payload)
