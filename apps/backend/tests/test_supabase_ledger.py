from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from talli_backend.adapters.supabase_ledger import (
    LedgerSupabaseConfiguration,
    SupabaseLedgerAdapter,
    SupabaseLedgerSession,
    SupabaseLedgerWorkflowTransaction,
    _VerifiedActor,
    _map_database_error,
)
from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.application.ledger_workflow import (
    RecordAdministrativeCostCommand,
    RecordInvestmentSaleFifoCommand,
)
from talli_backend.application.opening_snapshot_compatibility import (
    LegacyOpeningSnapshotCursor,
)
from talli_backend.modules.ledger.public import (
    AdministrativeCostCategory,
    BankInterestIncomeFacts,
    LedgerEntryId,
    LedgerEntryKind,
    LedgerError,
    LedgerFactReference,
    LedgerLine,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    PostManualJournalCommand,
    PostedLedgerEntry,
    ReconstructionEvidence,
    ReconstructionEvidenceIssuer,
    ReconstructionEvidenceKind,
    ReconstructionEvidenceStatus,
    ReconstructionState,
    RecognizeHoldingActionCommand,
    RecordReconstructionAssessmentCommand,
)
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    Money,
    Timestamp,
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


def reconstruction_command() -> RecordReconstructionAssessmentCommand:
    pairs = (
        ("PRIOR_CLOSING_OPENING", "LEDGER"),
        ("BANK_MOVEMENTS", "BANKING"),
        ("BANK_RECONCILIATION", "BANKING"),
        ("INVESTMENTS", "INVESTMENTS"),
        ("SHAREHOLDERS", "SHAREHOLDER_REGISTER_FILING"),
        ("LOANS", "BANKING"),
        ("LOANS", "CORPORATE_GOVERNANCE"),
        ("EQUITY", "CORPORATE_GOVERNANCE"),
        ("EQUITY", "SHAREHOLDER_REGISTER_FILING"),
        ("TAX_HISTORY", "COMPANY_TAX_FILING"),
        ("CURRENT_YEAR_ACTIVITY", "LEDGER"),
        ("DOCUMENTS", "DOCUMENTS"),
        ("UNSUPPORTED_ACTIVITY_CHECK", "COMPANY_ACCESS"),
    )
    as_of = LocalDate(date(2026, 8, 27))
    evidence = tuple(
        ReconstructionEvidence(
            kind=ReconstructionEvidenceKind(kind),
            issuer=ReconstructionEvidenceIssuer(issuer),
            confirmation=ReconstructionEvidenceStatus.CONFIRMED,
            source_record_id=LedgerSourceRecordId(f"source:{index}"),
            fact_sha256=f"{index:064x}",
            coverage_from=(
                LocalDate(date(2026, 1, 1))
                if kind in {"BANK_MOVEMENTS", "CURRENT_YEAR_ACTIVITY"}
                else None
            ),
            coverage_through=(
                as_of
                if kind in {"BANK_MOVEMENTS", "CURRENT_YEAR_ACTIVITY"}
                else None
            ),
        )
        for index, (kind, issuer) in enumerate(pairs)
    )
    return RecordReconstructionAssessmentCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("ledger-reconstruction-adapter"),
        idempotency_key=IdempotencyKey("reconstruction-adapter-2026-08-27"),
        income_year=IncomeYear(2026),
        as_of=as_of,
        evidence=evidence,
    )


def supported_pattern_command() -> RecognizeHoldingActionCommand:
    return RecognizeHoldingActionCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("supported-pattern-adapter"),
        idempotency_key=IdempotencyKey("supported-pattern-adapter-2026-08-27"),
        income_year=IncomeYear(2026),
        event_date=LocalDate(date(2026, 8, 27)),
        primary_source=LedgerFactReference(
            capability=LedgerSourceCapability.BANKING,
            record_id=LedgerSourceRecordId("bank-interest:2026:1"),
            revision=2,
            fact_sha256="a" * 64,
        ),
        corroborating_sources=(),
        facts=BankInterestIncomeFacts(amount=Money.nok("500.00")),
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


def bound_transaction() -> SupabaseLedgerWorkflowTransaction:
    session = bound_session()
    return SupabaseLedgerWorkflowTransaction(
        session._database_url,
        session._verified,
        None,  # type: ignore[arg-type]
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


def test_reconstruction_adapter_serializes_canonical_evidence_and_decodes_result() -> None:
    session = bound_session()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{
            "assessment_id": "40000000-0000-0000-0000-000000000004",
            "company_id": "10000000-0000-0000-0000-000000000001",
            "income_year": 2026,
            "as_of": date(2026, 8, 27),
            "state": "READY",
            "gap_codes": [],
            "evidence_digest": "a" * 64,
            "recorded_at": datetime(2026, 8, 27, 10, tzinfo=UTC),
            "replayed": False,
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    requested = reconstruction_command()
    result = asyncio.run(
        session.record_reconstruction_assessment(
            requested,
            evidence=requested.evidence,
            state=ReconstructionState.READY,
            gap_codes=(),
        )
    )

    assert result.state is ReconstructionState.READY
    assert "ledger.record_reconstruction_assessment" in calls[0][0]
    payload = json.loads(str(calls[0][1][4]))
    assert len(payload) == 13
    assert payload[1] == {
        "kind": "BANK_MOVEMENTS",
        "issuer": "BANKING",
        "confirmation": "CONFIRMED",
        "sourceRecordId": "source:1",
        "factSha256": f"{1:064x}",
        "coverageFrom": "2026-01-01",
        "coverageThrough": "2026-08-27",
        "gapCode": None,
    }


def test_supported_pattern_adapter_binds_rule_event_and_source_provenance() -> None:
    session = bound_session()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{
            "ledger_entry_id": "40000000-0000-0000-0000-000000000004",
            "company_id": "10000000-0000-0000-0000-000000000001",
            "income_year": 2026,
            "entry_kind": "BANK_INTEREST",
            "posted_at": datetime(2026, 8, 27, 10, tzinfo=UTC),
            "replayed": False,
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    requested = supported_pattern_command()
    result = asyncio.run(
        session.post_entry(
            requested,
            entry_kind=LedgerEntryKind.BANK_INTEREST,
            memo="Bank interest supported by bank advice",
            lines=(
                LedgerLine("1920", "Bank", Money.nok("500"), Money.nok("0")),
                LedgerLine("8050", "Interest", Money.nok("0"), Money.nok("500")),
            ),
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.BANKING,
            source_record_id=requested.primary_source.record_id,
        )
    )

    assert result.entry_kind is LedgerEntryKind.BANK_INTEREST
    assert "ledger.post_supported_entry_v1" in calls[0][0]
    assert calls[0][1][10] == date(2026, 8, 27)
    assert calls[0][1][11] == "ledger-supported-patterns-2026.1"
    assert json.loads(str(calls[0][1][12])) == [{
        "role": "PRIMARY",
        "capability": "BANKING",
        "recordId": "bank-interest:2026:1",
        "revision": 2,
        "factSha256": "a" * 64,
    }]


def test_writer_prepare_serializes_exact_camel_case_business_facts() -> None:
    transaction = bound_transaction()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{"result": {"replay": None}}]

    transaction._database_rows = database_rows  # type: ignore[method-assign]
    result = asyncio.run(
        transaction.prepare_administrative_cost(
            RecordAdministrativeCostCommand(
                company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
                actor_id=ACTOR_ID,
                correlation_id=CorrelationId("writer-adapter-admin"),
                idempotency_key=IdempotencyKey(
                    "31000000-0000-4000-8000-000000000003"
                ),
                income_year=IncomeYear(2026),
                bank_transaction_id=LedgerSourceRecordId(
                    "60000000-0000-0000-0000-000000000006"
                ),
                category=AdministrativeCostCategory.SOFTWARE,
                payee="Talli AS",
                amount=Money.nok("1490"),
                paid_date=LocalDate(date(2026, 8, 27)),
            )
        )
    )

    assert result == {"replay": None}
    assert "backend_system.prepare_administrative_cost_v1" in calls[0][0]
    assert json.loads(str(calls[0][1][0])) == {
        "companyId": "10000000-0000-0000-0000-000000000001",
        "incomeYear": 2026,
        "idempotencyKey": "31000000-0000-4000-8000-000000000003",
        "correlationId": "writer-adapter-admin",
        "bankTransactionId": "60000000-0000-0000-0000-000000000006",
        "category": "SOFTWARE",
        "payee": "Talli AS",
        "amount": "1490.00",
        "paidDate": "2026-08-27",
        "documentId": None,
    }
    assert calls[0][1][1] == str(ACTOR_ID.subject)


def test_writer_complete_binds_posted_entry_and_locked_fifo_facts() -> None:
    transaction = bound_transaction()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{"result": {"actionId": "71000000-0000-0000-0000-000000000007"}}]

    transaction._database_rows = database_rows  # type: ignore[method-assign]
    sale = RecordInvestmentSaleFifoCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("writer-adapter-sale"),
        idempotency_key=IdempotencyKey(
            "32000000-0000-4000-8000-000000000003"
        ),
        income_year=IncomeYear(2026),
        action_id=LedgerSourceRecordId(
            "71000000-0000-0000-0000-000000000007"
        ),
        position_id=LedgerSourceRecordId(
            "72000000-0000-0000-0000-000000000007"
        ),
        sale_date=LocalDate(date(2026, 8, 27)),
        sold_share_count=10,
        proceeds=Money.nok("12000"),
        bank_transaction_id=None,
        document_id=None,
        document_status="not_required",
    )
    posted = PostedLedgerEntry(
        entry_id=LedgerEntryId("40000000-0000-0000-0000-000000000004"),
        company_id=sale.company_id,
        income_year=sale.income_year,
        entry_kind=LedgerEntryKind.SHARE_SALE,
        posted_at=Timestamp(datetime(2026, 8, 27, 10, tzinfo=UTC)),
        replayed=False,
    )
    prepared = {
        "investmentName": "Eksempel AS",
        "fifoCostBasisReduction": "10000.00",
        "allocations": [{"lot_id": "73000000-0000-0000-0000-000000000007"}],
    }

    result = asyncio.run(
        transaction.complete_investment_sale_fifo(sale, posted, prepared)
    )

    assert result["actionId"] == str(sale.action_id)
    assert "backend_system.complete_investment_sale_fifo_v1" in calls[0][0]
    assert json.loads(str(calls[0][1][0]))["soldShareCount"] == 10
    assert calls[0][1][1] == str(posted.entry_id)
    assert json.loads(str(calls[0][1][2])) == prepared
    assert calls[0][1][3] == str(ACTOR_ID.subject)


def test_writer_adapter_fails_closed_on_non_object_database_result() -> None:
    transaction = bound_transaction()

    async def database_rows(
        _query: str, _parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        return [{"result": ["not", "an", "object"]}]

    transaction._database_rows = database_rows  # type: ignore[method-assign]
    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            transaction.prepare_administrative_cost(
                RecordAdministrativeCostCommand(
                    company_id=CompanyId(
                        "10000000-0000-0000-0000-000000000001"
                    ),
                    actor_id=ACTOR_ID,
                    correlation_id=CorrelationId("writer-adapter-malformed"),
                    idempotency_key=IdempotencyKey(
                        "33000000-0000-4000-8000-000000000003"
                    ),
                    income_year=IncomeYear(2026),
                    bank_transaction_id=LedgerSourceRecordId(
                        "60000000-0000-0000-0000-000000000006"
                    ),
                    category=AdministrativeCostCategory.BANK_FEE,
                    payee="Bank",
                    amount=Money.nok("89"),
                    paid_date=LocalDate(date(2026, 8, 27)),
                )
            )
        )
    assert failure.value.code == "LEDGER_DEPENDENCY_UNAVAILABLE"


def test_transaction_adapter_names_all_nine_exact_prepare_and_complete_routines() -> None:
    source = Path(__file__).parents[1].joinpath(
        "src/talli_backend/adapters/supabase_ledger.py"
    ).read_text(encoding="utf-8")
    for operation in (
        "administrative_cost",
        "investment_dividend",
        "shareholder_loan",
        "tax_settlement",
        "bank_transaction_suggestion",
        "investment_purchase_fifo",
        "investment_sale_fifo",
        "corporate_decision_finalization",
        "owner_dividend_payment",
    ):
        assert f"backend_system.prepare_{operation}_v1" in source
        assert f"backend_system.complete_{operation}_v1" in source


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


def opening_snapshot_payload() -> dict[str, object]:
    return {
        "setupId": "60000000-0000-0000-0000-000000000006",
        "companyId": "10000000-0000-0000-0000-000000000001",
        "incomeYear": 2026,
        "bankBalance": "9007199254740993.12",
        "shareCapital": "30000.00",
        "shareCount": 100,
        "nominalValue": "300.00",
        "lockedAt": "2026-08-27T10:00:00Z",
        "createdAt": "2026-08-27T09:00:00Z",
        "createdBy": str(ACTOR_ID.subject),
        "shareholders": [
            {
                "shareholderId": "70000000-0000-0000-0000-000000000007",
                "setupId": "60000000-0000-0000-0000-000000000006",
                "companyId": "10000000-0000-0000-0000-000000000001",
                "name": "Owner",
                "shareholderKind": "norwegian_person",
                "nationalId": "01010112345",
                "orgNumber": None,
                "shareCount": 100,
            }
        ],
    }


def test_opening_snapshot_query_binds_actor_scope_and_decodes_facts() -> None:
    session = bound_session()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{
            "items": [opening_snapshot_payload()],
            "next_cursor": "opaque-opening-next",
            "has_more": True,
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    company_id = CompanyId("10000000-0000-0000-0000-000000000001")
    snapshots = asyncio.run(
        session.list_opening_snapshots(
            actor_id=ACTOR_ID,
            company_ids=(company_id,),
            correlation_id=CorrelationId("opening-query-test"),
            cursor=None,
            limit=25,
        )
    )

    assert len(snapshots.items) == 1
    assert snapshots.items[0].company_id == company_id
    assert snapshots.items[0].bank_balance == Money.nok("9007199254740993.12")
    assert snapshots.items[0].shareholders[0].national_id == "01010112345"
    assert snapshots.next_cursor == LegacyOpeningSnapshotCursor("opaque-opening-next")
    assert snapshots.has_more is True
    assert "backend_system.list_opening_snapshots_legacy_v1" in calls[0][0]
    assert calls[0][1] == ([str(company_id)], None, 25, str(ACTOR_ID.subject))


def test_opening_snapshot_query_rejects_forged_actor_before_database_io() -> None:
    session = bound_session()

    async def forbidden_database(*_args: object, **_kwargs: object) -> list[object]:
        raise AssertionError("database must not be called")

    session._database_rows = forbidden_database  # type: ignore[method-assign]
    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            session.list_opening_snapshots(
                actor_id=OTHER_ACTOR,
                company_ids=(
                    CompanyId("10000000-0000-0000-0000-000000000001"),
                ),
                correlation_id=CorrelationId("opening-query-forged"),
                cursor=None,
                limit=100,
            )
        )
    assert failure.value.code == "LEDGER_FORBIDDEN"


def test_opening_snapshot_query_maps_inconsistent_facts_to_unavailable() -> None:
    session = bound_session()
    malformed = opening_snapshot_payload()
    malformed["shareholders"] = [
        {
            **malformed["shareholders"][0],  # type: ignore[index]
            "setupId": "60000000-0000-0000-0000-000000000099",
        }
    ]

    async def database_rows(
        _query: str, _parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        return [{"items": [malformed], "next_cursor": None, "has_more": False}]

    session._database_rows = database_rows  # type: ignore[method-assign]
    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            session.list_opening_snapshots(
                actor_id=ACTOR_ID,
                company_ids=(
                    CompanyId("10000000-0000-0000-0000-000000000001"),
                ),
                correlation_id=CorrelationId("opening-query-malformed"),
                cursor=None,
                limit=100,
            )
        )
    assert failure.value.code == "LEDGER_DEPENDENCY_UNAVAILABLE"
