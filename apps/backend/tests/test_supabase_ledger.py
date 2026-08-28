from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pytest
from talli_backend.adapters.supabase_ledger import (
    LedgerSupabaseConfiguration,
    SupabaseLedgerAdapter,
    SupabaseLedgerSession,
    SupabaseLedgerWorkflowTransaction,
    _map_database_error,
    _VerifiedActor,
)
from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.application.ledger_workflow import (
    NewYearStartCommand,
    RecordAdministrativeCostCommand,
    RecordInvestmentSaleFifoCommand,
)
from talli_backend.application.opening_snapshot_compatibility import (
    LegacyOpeningSnapshotCursor,
)
from talli_backend.modules.ledger import public as ledger_public
from talli_backend.modules.ledger.public import (
    AdministrativeCostCategory,
    AdministrativeCostCorrectionFacts,
    AdministrativeCostCorrectionScope,
    ApprovedLossCoverageCapitalReductionFacts,
    BankInterestIncomeFacts,
    BankLoanEvent,
    BankLoanMaturity,
    BankLoanReferenceId,
    CapitalIncreasePhase,
    CapitalIncreaseReferenceId,
    CapitalReductionRecognition,
    CashCapitalIncreaseFacts,
    CloseCompanyYearCommand,
    CompanyYearCloseEvidence,
    CompanyYearCloseEvidenceKind,
    CompanyYearCloseOutputKind,
    CompanyYearCloseOutputReference,
    CompanyYearCloseState,
    CompiledOpeningPositionComponent,
    CorrectHoldingActionCommand,
    DividendDecisionReferenceId,
    InvestmentDividendFacts,
    InvestmentDividendPhase,
    LedgerEntryId,
    LedgerEntryKind,
    LedgerError,
    LedgerFactReference,
    LedgerLine,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    OpeningBalanceCategory,
    OpeningBalanceComponent,
    OpeningBankLoanComponent,
    OpeningPositionMode,
    OrdinaryBankLoanFacts,
    PostedLedgerEntry,
    PostManualJournalCommand,
    RebuildCompanyYearOpeningCommand,
    RecognizeHoldingActionCommand,
    ReconstructionAssessmentId,
    ReconstructionEvidence,
    ReconstructionEvidenceIssuer,
    ReconstructionEvidenceKind,
    ReconstructionEvidenceStatus,
    ReconstructionState,
    RecordReconstructionAssessmentCommand,
)
from talli_backend.modules.shareholder_register_filing.public import OpeningShareholder
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
            source_revision=index + 1,
            fact_sha256=f"{index:064x}",
            coverage_from=LocalDate(date(2026, 1, 1)),
            coverage_through=as_of,
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
        economic_fact_entry_ids=(
            LedgerEntryId("50000000-0000-0000-0000-000000000005"),
        ),
    )


def opening_position_command() -> RebuildCompanyYearOpeningCommand:
    bank = OpeningBalanceComponent(
        category=OpeningBalanceCategory.BANK,
        reference_id=LedgerSourceRecordId("bank-account:1"),
        amount=Money.nok("105000.00"),
        primary_source=LedgerFactReference(
            capability=LedgerSourceCapability.BANKING,
            record_id=LedgerSourceRecordId("bank-balance:1"),
            revision=1,
            fact_sha256="1" * 64,
        ),
        corroborating_sources=(LedgerFactReference(
            capability=LedgerSourceCapability.DOCUMENTS,
            record_id=LedgerSourceRecordId("bank-document:1"),
            revision=1,
            fact_sha256="2" * 64,
        ),),
    )
    loan = OpeningBankLoanComponent(
        loan_reference_id=BankLoanReferenceId("bank-loan:prior-year:1"),
        maturity=BankLoanMaturity.LONG_TERM,
        amount=Money.nok("75000.00"),
        primary_source=LedgerFactReference(
            capability=LedgerSourceCapability.BANKING,
            record_id=LedgerSourceRecordId("bank-loan-statement:2025:1"),
            revision=1,
            fact_sha256="3" * 64,
        ),
        corroborating_sources=(LedgerFactReference(
            capability=LedgerSourceCapability.DOCUMENTS,
            record_id=LedgerSourceRecordId("bank-loan-agreement:1"),
            revision=2,
            fact_sha256="4" * 64,
        ),),
    )
    capital = OpeningBalanceComponent(
        category=OpeningBalanceCategory.REGISTERED_SHARE_CAPITAL,
        reference_id=LedgerSourceRecordId("share-capital"),
        amount=Money.nok("30000.00"),
        primary_source=LedgerFactReference(
            capability=LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING,
            record_id=LedgerSourceRecordId("share-capital:2025"),
            revision=1,
            fact_sha256="5" * 64,
        ),
        corroborating_sources=(LedgerFactReference(
            capability=LedgerSourceCapability.DOCUMENTS,
            record_id=LedgerSourceRecordId("share-capital-document:2025"),
            revision=1,
            fact_sha256="6" * 64,
        ),),
    )
    return RebuildCompanyYearOpeningCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("ledger-opening-position-adapter"),
        idempotency_key=IdempotencyKey("opening-position-adapter-2026"),
        income_year=IncomeYear(2026),
        opening_date=LocalDate(date(2026, 1, 1)),
        mode=OpeningPositionMode.PRIOR_CLOSE_RECONSTRUCTION,
        opening_basis=LedgerFactReference(
            capability=LedgerSourceCapability.ANNUAL_ACCOUNTS_FILING,
            record_id=LedgerSourceRecordId("prior-close:2025"),
            revision=1,
            fact_sha256="0" * 64,
        ),
        components=(bank, loan, capital),
    )


def new_year_start_command() -> NewYearStartCommand:
    opening = opening_position_command()
    return NewYearStartCommand(
        company_id=opening.company_id,
        actor_id=opening.actor_id,
        correlation_id=opening.correlation_id,
        idempotency_key=opening.idempotency_key,
        income_year=opening.income_year,
        bank_balance=Money.nok("30000.00"),
        share_capital=Money.nok("30000.00"),
        opening_mode=opening.mode,
        opening_basis=opening.opening_basis,
        opening_components=opening.components,
        share_count=100,
        nominal_value=Money.nok("300.00"),
        shareholders=(OpeningShareholder(
            name="Owner",
            shareholder_kind="norwegian_person",
            national_id="01010112345",
            org_number=None,
            share_count=100,
        ),),
    )


def test_new_year_completion_persists_the_exact_claimed_typed_request() -> None:
    transaction = bound_transaction()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{"completed": True}]

    transaction._database_rows = database_rows  # type: ignore[method-assign]
    request = {
        "companyId": str(new_year_start_command().company_id),
        "incomeYear": 2026,
        "openingMode": "PRIOR_CLOSE_RECONSTRUCTION",
        "openingComponents": [{"componentKind": "CLASSIFIED_BALANCE"}],
    }
    asyncio.run(transaction.complete_workflow(
        operation_name="new_year_start",
        command=new_year_start_command(),
        request=request,
        result={"entryId": "40000000-0000-0000-0000-000000000007"},
    ))

    assert "complete_ledger_workflow_v1" in calls[0][0]
    assert json.loads(str(calls[0][1][3])) == request


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


def received_dividend_command(
    phase: InvestmentDividendPhase,
    *,
    decision_entry_id: LedgerEntryId | None = None,
    decision_reference_id: DividendDecisionReferenceId | None = None,
) -> RecognizeHoldingActionCommand:
    decision = phase is InvestmentDividendPhase.FINAL_DECISION
    corroborating_capabilities = (
        (
            LedgerSourceCapability.DOCUMENTS,
            LedgerSourceCapability.COMPANY_TAX_FILING,
        )
        if decision
        else (LedgerSourceCapability.BANKING,)
    )
    return RecognizeHoldingActionCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId(f"received-dividend-{phase.value.lower()}"),
        idempotency_key=IdempotencyKey(
            f"received-dividend-{phase.value.lower()}-2026"
        ),
        income_year=IncomeYear(2026),
        event_date=LocalDate(date(2026, 8, 27)),
        primary_source=LedgerFactReference(
            capability=LedgerSourceCapability.INVESTMENTS,
            record_id=LedgerSourceRecordId(
                f"investment-dividend:{phase.value.lower()}:1"
            ),
            revision=2,
            fact_sha256="d" * 64,
        ),
        corroborating_sources=tuple(
            LedgerFactReference(
                capability=capability,
                record_id=LedgerSourceRecordId(
                    f"{capability.value.lower()}:dividend:1"
                ),
                revision=1,
                fact_sha256=f"{index + 1:064x}",
            )
            for index, capability in enumerate(corroborating_capabilities)
        ),
        facts=InvestmentDividendFacts(
            phase=phase,
            gross_amount=Money.nok("500.00"),
            decision_entry_id=decision_entry_id,
            decision_reference_id=decision_reference_id,
        ),
    )


def bank_loan_command(event: BankLoanEvent) -> RecognizeHoldingActionCommand:
    return RecognizeHoldingActionCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId(f"bank-loan-{event.value.lower()}"),
        idempotency_key=IdempotencyKey(f"bank-loan-{event.value.lower()}-2026"),
        income_year=IncomeYear(2026),
        event_date=LocalDate(date(2026, 8, 27)),
        primary_source=LedgerFactReference(
            capability=LedgerSourceCapability.BANKING,
            record_id=LedgerSourceRecordId(f"bank-transaction:{event.value.lower()}:1"),
            revision=2,
            fact_sha256="b" * 64,
        ),
        corroborating_sources=(
            LedgerFactReference(
                capability=LedgerSourceCapability.DOCUMENTS,
                record_id=LedgerSourceRecordId("bank-loan-agreement:1"),
                revision=1,
                fact_sha256="c" * 64,
            ),
        ),
        facts=OrdinaryBankLoanFacts(
            event=event,
            loan_reference_id=BankLoanReferenceId("bank-loan:1"),
            principal=Money.nok("100.00"),
            interest=Money.nok(
                "20.00" if event is BankLoanEvent.PAYMENT else "0.00"
            ),
            fee=Money.nok("5.00" if event is BankLoanEvent.PAYMENT else "0.00"),
        ),
    )


def cash_capital_increase_command(
    phase: CapitalIncreasePhase,
) -> RecognizeHoldingActionCommand:
    corroborating_capabilities = {
        CapitalIncreasePhase.BINDING_SUBSCRIPTION: (
            LedgerSourceCapability.DOCUMENTS,
        ),
        CapitalIncreasePhase.RESTRICTED_PAYMENT: (
            LedgerSourceCapability.BANKING,
            LedgerSourceCapability.DOCUMENTS,
        ),
        CapitalIncreasePhase.REGISTERED: (
            LedgerSourceCapability.BANKING,
            LedgerSourceCapability.DOCUMENTS,
            LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING,
        ),
    }[phase]
    return RecognizeHoldingActionCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId(f"cash-capital-{phase.value.lower()}"),
        idempotency_key=IdempotencyKey(f"cash-capital-{phase.value.lower()}-2026"),
        income_year=IncomeYear(2026),
        event_date=LocalDate(date(2026, 8, 27)),
        primary_source=LedgerFactReference(
            capability=LedgerSourceCapability.CORPORATE_GOVERNANCE,
            record_id=LedgerSourceRecordId(f"capital:{phase.value.lower()}:1"),
            revision=2,
            fact_sha256="d" * 64,
        ),
        corroborating_sources=tuple(
            LedgerFactReference(
                capability=capability,
                record_id=LedgerSourceRecordId(
                    f"{capability.value.lower()}:capital:{phase.value.lower()}:1"
                ),
                revision=1,
                fact_sha256=f"{index + 1:064x}",
            )
            for index, capability in enumerate(corroborating_capabilities)
        ),
        facts=CashCapitalIncreaseFacts(
            phase=phase,
            capital_increase_reference_id=CapitalIncreaseReferenceId(
                "capital-increase:1"
            ),
            nominal_increase=Money.nok("100.00"),
            share_premium=Money.nok("25.00"),
        ),
    )


def capital_reduction_reference_id() -> object:
    reference_type = getattr(
        ledger_public,
        "CapitalReductionReferenceId",
        LedgerSourceRecordId,
    )
    return reference_type("capital-reduction:loss-coverage:1")


def registered_capital_reduction_recognition() -> CapitalReductionRecognition:
    return getattr(
        CapitalReductionRecognition,
        "REGISTERED",
        cast(CapitalReductionRecognition, "REGISTERED"),
    )


def capital_reduction_command(
    recognition: CapitalReductionRecognition,
) -> RecognizeHoldingActionCommand:
    fields: dict[str, object] = {
        "recognition": recognition,
        "nominal_reduction": Money.nok("100.00"),
    }
    if (
        "capital_reduction_reference_id"
        in ApprovedLossCoverageCapitalReductionFacts.__dataclass_fields__
    ):
        fields["capital_reduction_reference_id"] = capital_reduction_reference_id()
    corroborating_capabilities = [LedgerSourceCapability.DOCUMENTS]
    if recognition is not CapitalReductionRecognition.DECIDED_NOT_REGISTERED:
        corroborating_capabilities.append(
            LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING
        )
    return RecognizeHoldingActionCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId(f"capital-reduction-{str(recognition).lower()}"),
        idempotency_key=IdempotencyKey(
            f"capital-reduction-{str(recognition).lower()}-2026"
        ),
        income_year=IncomeYear(2026),
        event_date=LocalDate(date(2026, 8, 27)),
        primary_source=LedgerFactReference(
            capability=LedgerSourceCapability.CORPORATE_GOVERNANCE,
            record_id=LedgerSourceRecordId(
                f"capital-reduction:{str(recognition).lower()}:1"
            ),
            revision=2,
            fact_sha256="e" * 64,
        ),
        corroborating_sources=tuple(
            LedgerFactReference(
                capability=capability,
                record_id=LedgerSourceRecordId(
                    f"{capability.value.lower()}:capital-reduction:1"
                ),
                revision=1,
                fact_sha256=f"{index + 1:064x}",
            )
            for index, capability in enumerate(corroborating_capabilities)
        ),
        facts=ApprovedLossCoverageCapitalReductionFacts(**fields),  # type: ignore[arg-type]
    )


def correction_command() -> CorrectHoldingActionCommand:
    return CorrectHoldingActionCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("guided-correction-adapter"),
        idempotency_key=IdempotencyKey("guided-correction-adapter-0001"),
        income_year=IncomeYear(2026),
        event_date=LocalDate(date(2026, 8, 27)),
        original_entry_id=LedgerEntryId("40000000-0000-0000-0000-000000000004"),
        reason="Wrong documented business category",
        primary_source=LedgerFactReference(
            capability=LedgerSourceCapability.DOCUMENTS,
            record_id=LedgerSourceRecordId("correction-document:1"),
            revision=1,
            fact_sha256="c" * 64,
        ),
        corroborating_sources=(
            LedgerFactReference(
                capability=LedgerSourceCapability.BANKING,
                record_id=LedgerSourceRecordId("correction-bank-match:1"),
                revision=2,
                fact_sha256="d" * 64,
            ),
        ),
        replacement=AdministrativeCostCorrectionFacts(
            category=AdministrativeCostCategory.LEGAL_ADVISORY,
            supplier_name="Advokat AS",
            document_date=LocalDate(date(2026, 8, 20)),
            delivery_date=LocalDate(date(2026, 8, 19)),
            description="Legal advice for the holding company",
            business_purpose="Documented corporate legal advice",
            amount=Money.nok("1250.00"),
            payment_confirmed=True,
            correction_scope=(
                AdministrativeCostCorrectionScope.CURRENT_COMPANY_YEAR
            ),
            blocks=(),
        ),
    )


def close_company_year_command() -> CloseCompanyYearCommand:
    outputs = tuple(
        CompanyYearCloseOutputReference(
            kind=kind,
            source_record_id=LedgerSourceRecordId(
                f"close-output:{kind.value.lower()}"
            ),
            revision=1,
            fact_sha256=kind.value.encode().hex().ljust(64, "0")[:64],
            economic_facts_digest="e" * 64,
        )
        for kind in CompanyYearCloseOutputKind
    )
    return CloseCompanyYearCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("company-year-close-adapter"),
        idempotency_key=IdempotencyKey("company-year-close-adapter-0001"),
        income_year=IncomeYear(2026),
        period_end=LocalDate(date(2026, 12, 31)),
        reason="Documented company-year close",
        reconstruction_assessment_id=ReconstructionAssessmentId(
            "70000000-0000-0000-0000-000000000007"
        ),
        reconstruction_evidence_digest="a" * 64,
        evidence=(
            CompanyYearCloseEvidence(
                kind=CompanyYearCloseEvidenceKind.BANK_ROWS_RESOLVED,
                issuer=LedgerSourceCapability.BANKING,
                source_record_id=LedgerSourceRecordId("close:bank-rows"),
                revision=1,
                fact_sha256="b" * 64,
                ledger_state_digest="d" * 64,
                coverage_through=LocalDate(date(2026, 12, 31)),
                confirmation=ReconstructionEvidenceStatus.CONFIRMED,
            ),
            CompanyYearCloseEvidence(
                kind=CompanyYearCloseEvidenceKind.MATERIAL_BALANCES_DOCUMENTED,
                issuer=LedgerSourceCapability.DOCUMENTS,
                source_record_id=LedgerSourceRecordId("close:material-balances"),
                revision=1,
                fact_sha256="c" * 64,
                ledger_state_digest="d" * 64,
                coverage_through=LocalDate(date(2026, 12, 31)),
                confirmation=ReconstructionEvidenceStatus.CONFIRMED,
            ),
            CompanyYearCloseEvidence(
                kind=CompanyYearCloseEvidenceKind.REPORTING_RECONCILED,
                issuer=LedgerSourceCapability.LEDGER,
                source_record_id=LedgerSourceRecordId("close:reporting"),
                revision=1,
                fact_sha256="e" * 64,
                ledger_state_digest="d" * 64,
                coverage_through=LocalDate(date(2026, 12, 31)),
                confirmation=ReconstructionEvidenceStatus.CONFIRMED,
                outputs=outputs,
            ),
        ),
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
    assert result.source_evidence_digest == "a" * 64
    assert result.source_evidence_count == 13
    assert "ledger.record_reconstruction_assessment" in calls[0][0]
    payload = json.loads(str(calls[0][1][4]))
    assert len(payload) == 13
    assert payload[1] == {
        "kind": "BANK_MOVEMENTS",
        "issuer": "BANKING",
        "confirmation": "CONFIRMED",
        "sourceRecordId": "source:1",
        "sourceRevision": 2,
        "factSha256": f"{1:064x}",
        "coverageFrom": "2026-01-01",
        "coverageThrough": "2026-08-27",
        "gapCode": None,
    }
    assert calls[0][1][5] == ["50000000-0000-0000-0000-000000000005"]


def test_reconstruction_read_requires_the_source_evidence_binding_pair() -> None:
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
            "ledger_state_digest": "b" * 64,
            "source_evidence_digest": "a" * 64,
            "source_evidence_count": 13,
            "economic_facts_digest": "c" * 64,
            "economic_fact_count": 1,
            "recorded_at": datetime(2026, 8, 27, 10, tzinfo=UTC),
            "replayed": False,
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    result = asyncio.run(
        session.get_reconstruction_assessment(
            actor_id=ACTOR_ID,
            company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
            income_year=IncomeYear(2026),
            correlation_id=CorrelationId("reconstruction-source-evidence-query"),
        )
    )

    assert result.source_evidence_digest == "a" * 64
    assert result.source_evidence_count == 13
    assert "get_reconstruction_assessment_with_source_evidence_v1" in calls[0][0]


def test_reconstruction_candidate_query_is_member_scoped_and_typed() -> None:
    session = bound_session()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{
            "entry_ids": [
                "50000000-0000-0000-0000-000000000005",
                "50000000-0000-0000-0000-000000000006",
            ],
            "facts_digest": "e" * 64,
            "fact_count": 2,
            "facts": [],
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    result = asyncio.run(session.get_reconstruction_economic_fact_candidates(
        actor_id=ACTOR_ID,
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        income_year=IncomeYear(2026),
        as_of=LocalDate(date(2026, 8, 27)),
        correlation_id=CorrelationId("reconstruction-candidates-adapter"),
    ))

    assert tuple(str(entry_id) for entry_id in result.entry_ids) == (
        "50000000-0000-0000-0000-000000000005",
        "50000000-0000-0000-0000-000000000006",
    )
    assert result.facts_digest == "e" * 64
    assert "get_company_year_economic_fact_candidates_v1" in calls[0][0]


def test_reconstruction_economic_fact_snapshot_decodes_canonical_fact() -> None:
    session = bound_session()
    fact: dict[str, object] = {
        "entryId": "50000000-0000-0000-0000-000000000005",
        "eventDate": "2026-01-01",
        "entryKind": "OPENING_BALANCE",
        "memo": "Complete evidenced opening position",
        "lines": [
            {"account": "1920", "description": "Bank", "debit": "1.00", "credit": "0.00", "currency": "NOK"},
            {"account": "2050", "description": "Equity", "debit": "0.00", "credit": "1.00", "currency": "NOK"},
        ],
        "correlationId": "opening-position-snapshot",
        "ruleVersion": "ledger-supported-patterns-2026.1",
        "sources": [{
            "role": "PRIMARY",
            "capability": "ANNUAL_ACCOUNTS_FILING",
            "recordId": "prior-close:2025",
            "revision": 1,
            "factSha256": "a" * 64,
        }],
        "corrections": [],
        "postedBy": str(ACTOR_ID.subject),
        "postedAt": "2026-08-27T10:00:00+00:00",
    }

    async def database_rows(
        _query: str, _parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        return [{
            "assessment_id": "40000000-0000-0000-0000-000000000004",
            "company_id": "10000000-0000-0000-0000-000000000001",
            "income_year": 2026,
            "as_of": date(2026, 8, 27),
            "facts_digest": "f" * 64,
            "fact_count": 1,
            "facts": [fact],
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    snapshot = asyncio.run(session.get_reconstruction_economic_facts(
        actor_id=ACTOR_ID,
        assessment_id=ReconstructionAssessmentId(
            "40000000-0000-0000-0000-000000000004"
        ),
        correlation_id=CorrelationId("economic-fact-snapshot-adapter"),
    ))

    assert snapshot.facts_digest == "f" * 64
    assert snapshot.facts[0].entry_kind is LedgerEntryKind.OPENING_BALANCE
    assert snapshot.facts[0].sources[0].revision == 1

    malformed_fact = dict(fact)
    malformed_fact["sources"] = [*fact["sources"], "silently-dropped-source"]
    with pytest.raises(ValueError):
        session._reconstruction_economic_fact(malformed_fact)


def test_opening_position_adapter_binds_atomic_component_rpc() -> None:
    session = bound_session()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{
            "ledger_entry_id": "50000000-0000-0000-0000-000000000005",
            "company_id": "10000000-0000-0000-0000-000000000001",
            "income_year": 2026,
            "entry_kind": "OPENING_BALANCE",
            "posted_at": datetime(2026, 8, 27, 10, tzinfo=UTC),
            "replayed": False,
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    requested = opening_position_command()
    lines = (
        LedgerLine("1920", "Bank balance: bank-account:1", Money.nok("105000"), Money.nok("0")),
        LedgerLine("2220", "Long-term bank loan payable: bank-loan:prior-year:1", Money.nok("0"), Money.nok("75000")),
        LedgerLine("2000", "Registered share capital: share-capital", Money.nok("0"), Money.nok("30000")),
    )
    compiled = (
        CompiledOpeningPositionComponent(
            component_kind="CLASSIFIED_BALANCE",
            category=OpeningBalanceCategory.BANK,
            reference_id="bank-account:1",
            lifecycle_phase=None,
            amount=Money.nok("105000"),
            account="1920",
            description="Bank balance",
            is_debit=True,
            primary_source=requested.components[0].primary_source,
            corroborating_sources=requested.components[0].corroborating_sources,
        ),
        CompiledOpeningPositionComponent(
            component_kind="BANK_LOAN",
            category=OpeningBalanceCategory.LONG_TERM_BANK_LOAN_PAYABLE,
            reference_id="bank-loan:prior-year:1",
            lifecycle_phase="LONG_TERM",
            amount=Money.nok("75000"),
            account="2220",
            description="Long-term bank loan payable",
            is_debit=False,
            primary_source=requested.components[1].primary_source,
            corroborating_sources=requested.components[1].corroborating_sources,
        ),
        CompiledOpeningPositionComponent(
            component_kind="CLASSIFIED_BALANCE",
            category=OpeningBalanceCategory.REGISTERED_SHARE_CAPITAL,
            reference_id="share-capital",
            lifecycle_phase=None,
            amount=Money.nok("30000"),
            account="2000",
            description="Registered share capital",
            is_debit=False,
            primary_source=requested.components[2].primary_source,
            corroborating_sources=requested.components[2].corroborating_sources,
        ),
    )
    entry_sources = (
        requested.opening_basis,
        *(
            source
            for component in requested.components
            for source in (component.primary_source, *component.corroborating_sources)
        ),
    )
    result = asyncio.run(
        session.rebuild_company_year_opening(
            requested,
            components=compiled,
            lines=lines,
            entry_sources=entry_sources,
        )
    )

    assert result.entry_kind is LedgerEntryKind.OPENING_BALANCE
    assert "ledger.rebuild_company_year_opening_v1" in calls[0][0]
    parameters = calls[0][1]
    assert parameters[:5] == (
        "opening-position-adapter-2026",
        "10000000-0000-0000-0000-000000000001",
        2026,
        date(2026, 1, 1),
        "PRIOR_CLOSE_RECONSTRUCTION",
    )
    assert parameters[5] == "Complete evidenced opening position"
    components = json.loads(str(parameters[12]))
    assert [component["category"] for component in components] == [
        "BANK", "LONG_TERM_BANK_LOAN_PAYABLE", "REGISTERED_SHARE_CAPITAL"
    ]
    assert components[1]["componentKind"] == "BANK_LOAN"
    assert components[1]["lifecyclePhase"] == "LONG_TERM"
    assert components[1]["account"] == "2220"


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


@pytest.mark.parametrize(
    ("phase", "method_name", "function_name", "decision_entry_id"),
    [
        (
            InvestmentDividendPhase.FINAL_DECISION,
            "record_received_dividend_decision",
            "record_received_dividend_decision_v1",
            None,
        ),
        (
            InvestmentDividendPhase.PAYMENT,
            "record_received_dividend_payment",
            "record_received_dividend_payment_v1",
            LedgerEntryId("40000000-0000-0000-0000-000000000004"),
        ),
    ],
)
def test_received_dividend_adapter_binds_dedicated_lifecycle_rpc(
    phase: InvestmentDividendPhase,
    method_name: str,
    function_name: str,
    decision_entry_id: LedgerEntryId | None,
) -> None:
    session = bound_session()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{
            "ledger_entry_id": "40000000-0000-0000-0000-000000000005",
            "company_id": "10000000-0000-0000-0000-000000000001",
            "income_year": 2026,
            "entry_kind": "DIVIDEND_RECEIVED",
            "posted_at": datetime(2026, 8, 27, 10, tzinfo=UTC),
            "replayed": False,
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    requested = received_dividend_command(
        phase, decision_entry_id=decision_entry_id
    )
    kwargs: dict[str, object] = {
        "memo": "Received-dividend lifecycle",
        "lines": (
            LedgerLine("1530", "Debit", Money.nok("500"), Money.nok("0")),
            LedgerLine("8070", "Credit", Money.nok("0"), Money.nok("500")),
        ),
    }
    if decision_entry_id is not None:
        kwargs["decision_reference"] = decision_entry_id

    result = asyncio.run(getattr(session, method_name)(requested, **kwargs))

    assert result.entry_kind is LedgerEntryKind.DIVIDEND_RECEIVED
    assert f"ledger.{function_name}" in calls[0][0]
    parameters = calls[0][1]
    source_index = 12 if decision_entry_id is not None else 11
    if decision_entry_id is not None:
        assert parameters[3] == str(decision_entry_id)
    assert parameters[source_index - 1] == "ledger-supported-patterns-2026.1"
    sources = json.loads(str(parameters[source_index]))
    assert sources[0]["capability"] == "INVESTMENTS"
    assert sources[0]["role"] == "PRIMARY"


def test_received_dividend_adapter_uses_stable_opening_reference_rpc() -> None:
    session = bound_session()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{
            "ledger_entry_id": "40000000-0000-0000-0000-000000000005",
            "company_id": "10000000-0000-0000-0000-000000000001",
            "income_year": 2026,
            "entry_kind": "DIVIDEND_RECEIVED",
            "posted_at": datetime(2026, 8, 27, 10, tzinfo=UTC),
            "replayed": False,
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    reference = DividendDecisionReferenceId("dividend:opening:1")
    requested = received_dividend_command(
        InvestmentDividendPhase.PAYMENT,
        decision_reference_id=reference,
    )
    result = asyncio.run(session.record_received_dividend_payment(
        requested,
        decision_reference=reference,
        memo="Opening received-dividend settlement",
        lines=(
            LedgerLine("1920", "Bank", Money.nok("500"), Money.nok("0")),
            LedgerLine("1530", "Receivable", Money.nok("0"), Money.nok("500")),
        ),
    ))

    assert result.entry_kind is LedgerEntryKind.DIVIDEND_RECEIVED
    assert "ledger.record_received_dividend_payment_by_reference_v1" in calls[0][0]
    assert calls[0][1][3] == "dividend:opening:1"
    assert calls[0][1][11] == "ledger-supported-patterns-2026.1"
    sources = json.loads(str(calls[0][1][12]))
    assert [source["capability"] for source in sources] == [
        "INVESTMENTS", "BANKING"
    ]


@pytest.mark.parametrize(
    ("event", "method_name", "function_name", "rule_index", "sources_index"),
    [
        (
            BankLoanEvent.DISBURSEMENT,
            "record_bank_loan_disbursement",
            "record_bank_loan_disbursement_v1",
            12,
            13,
        ),
        (
            BankLoanEvent.PAYMENT,
            "record_bank_loan_payment",
            "record_bank_loan_payment_v1",
            14,
            15,
        ),
    ],
)
def test_bank_loan_adapter_binds_dedicated_lifecycle_rpc(
    event: BankLoanEvent,
    method_name: str,
    function_name: str,
    rule_index: int,
    sources_index: int,
) -> None:
    session = bound_session()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{
            "ledger_entry_id": "40000000-0000-0000-0000-000000000006",
            "company_id": "10000000-0000-0000-0000-000000000001",
            "income_year": 2026,
            "entry_kind": "BANK_LOAN",
            "posted_at": datetime(2026, 8, 27, 10, tzinfo=UTC),
            "replayed": False,
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    requested = bank_loan_command(event)
    kwargs: dict[str, object] = {
        "loan_reference_id": BankLoanReferenceId("bank-loan:1"),
        "principal": Money.nok("100.00"),
        "memo": "Ordinary NOK bank loan",
        "lines": (
            LedgerLine("1920", "Bank", Money.nok("100"), Money.nok("0")),
            LedgerLine("2220", "Principal", Money.nok("0"), Money.nok("100")),
        ),
    }
    if event is BankLoanEvent.PAYMENT:
        kwargs.update(
            interest=Money.nok("20.00"),
            fee=Money.nok("5.00"),
            lines=(
                LedgerLine("2220", "Principal", Money.nok("100"), Money.nok("0")),
                LedgerLine("8150", "Interest", Money.nok("20"), Money.nok("0")),
                LedgerLine("7770", "Fee", Money.nok("5"), Money.nok("0")),
                LedgerLine("1920", "Bank", Money.nok("0"), Money.nok("125")),
            ),
        )

    result = asyncio.run(getattr(session, method_name)(requested, **kwargs))

    assert result.entry_kind is LedgerEntryKind.BANK_LOAN
    assert f"ledger.{function_name}" in calls[0][0]
    parameters = calls[0][1]
    assert parameters[3] == "bank-loan:1"
    assert parameters[rule_index] == "ledger-supported-patterns-2026.1"
    sources = json.loads(str(parameters[sources_index]))
    assert [source["capability"] for source in sources] == ["BANKING", "DOCUMENTS"]
    assert [source["role"] for source in sources] == ["PRIMARY", "CORROBORATING"]


@pytest.mark.parametrize(
    ("loan_reference_id", "principal", "lines"),
    [
        (
            BankLoanReferenceId("bank-loan:wrong"),
            Money.nok("100.00"),
            (
                LedgerLine("2220", "Principal", Money.nok("100"), Money.nok("0")),
                LedgerLine("8150", "Interest", Money.nok("20"), Money.nok("0")),
                LedgerLine("7770", "Fee", Money.nok("5"), Money.nok("0")),
                LedgerLine("1920", "Bank", Money.nok("0"), Money.nok("125")),
            ),
        ),
        (
            BankLoanReferenceId("bank-loan:1"),
            Money.nok("99.00"),
            (
                LedgerLine("2220", "Principal", Money.nok("99"), Money.nok("0")),
                LedgerLine("8150", "Interest", Money.nok("20"), Money.nok("0")),
                LedgerLine("7770", "Fee", Money.nok("5"), Money.nok("0")),
                LedgerLine("1920", "Bank", Money.nok("0"), Money.nok("124")),
            ),
        ),
        (
            BankLoanReferenceId("bank-loan:1"),
            Money.nok("100.00"),
            (
                LedgerLine("2220", "Principal", Money.nok("100"), Money.nok("0")),
                LedgerLine("1920", "Bank", Money.nok("0"), Money.nok("100")),
            ),
        ),
    ],
)
def test_bank_loan_adapter_rejects_lifecycle_binding_mismatches_before_sql(
    loan_reference_id: BankLoanReferenceId,
    principal: Money,
    lines: tuple[LedgerLine, ...],
) -> None:
    session = bound_session()

    async def forbidden_database(*_args: object, **_kwargs: object) -> list[object]:
        raise AssertionError("database must not be called")

    session._database_rows = forbidden_database  # type: ignore[method-assign]
    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            session.record_bank_loan_payment(
                bank_loan_command(BankLoanEvent.PAYMENT),
                loan_reference_id=loan_reference_id,
                principal=principal,
                interest=Money.nok("20.00"),
                fee=Money.nok("5.00"),
                memo="Ordinary NOK bank loan",
                lines=lines,
            )
        )

    assert failure.value.code == "LEDGER_INVALID_INPUT"


@pytest.mark.parametrize(
    ("phase", "method_name", "function_name", "lines", "expected_capabilities"),
    [
        (
            CapitalIncreasePhase.BINDING_SUBSCRIPTION,
            "record_cash_capital_increase_subscription",
            "record_cash_capital_increase_subscription_v1",
            (
                LedgerLine("1500", "Receivable", Money.nok("125"), Money.nok("0")),
                LedgerLine("2030", "Unregistered", Money.nok("0"), Money.nok("125")),
            ),
            ("CORPORATE_GOVERNANCE", "DOCUMENTS"),
        ),
        (
            CapitalIncreasePhase.RESTRICTED_PAYMENT,
            "record_cash_capital_increase_restricted_payment",
            "record_cash_capital_increase_restricted_payment_v1",
            (
                LedgerLine("1921", "Restricted", Money.nok("125"), Money.nok("0")),
                LedgerLine("1500", "Receivable", Money.nok("0"), Money.nok("125")),
            ),
            ("CORPORATE_GOVERNANCE", "BANKING", "DOCUMENTS"),
        ),
        (
            CapitalIncreasePhase.REGISTERED,
            "record_cash_capital_increase_registration",
            "record_cash_capital_increase_registration_v1",
            (
                LedgerLine("2030", "Unregistered", Money.nok("125"), Money.nok("0")),
                LedgerLine("2000", "Capital", Money.nok("0"), Money.nok("100")),
                LedgerLine("2020", "Premium", Money.nok("0"), Money.nok("25")),
                LedgerLine("1920", "Bank", Money.nok("125"), Money.nok("0")),
                LedgerLine("1921", "Restricted", Money.nok("0"), Money.nok("125")),
            ),
            (
                "CORPORATE_GOVERNANCE",
                "BANKING",
                "DOCUMENTS",
                "SHAREHOLDER_REGISTER_FILING",
            ),
        ),
    ],
)
def test_cash_capital_increase_adapter_binds_exact_phase_rpc(
    phase: CapitalIncreasePhase,
    method_name: str,
    function_name: str,
    lines: tuple[LedgerLine, ...],
    expected_capabilities: tuple[str, ...],
) -> None:
    session = bound_session()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{
            "ledger_entry_id": "40000000-0000-0000-0000-000000000007",
            "company_id": "10000000-0000-0000-0000-000000000001",
            "income_year": 2026,
            "entry_kind": "CAPITAL_INCREASE",
            "posted_at": datetime(2026, 8, 27, 10, tzinfo=UTC),
            "replayed": False,
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    result = asyncio.run(
        getattr(session, method_name)(
            cash_capital_increase_command(phase),
            capital_increase_reference_id=CapitalIncreaseReferenceId(
                "capital-increase:1"
            ),
            nominal_increase=Money.nok("100.00"),
            share_premium=Money.nok("25.00"),
            memo="Cash capital increase",
            lines=lines,
        )
    )

    assert result.entry_kind is LedgerEntryKind.CAPITAL_INCREASE
    assert f"ledger.{function_name}" in calls[0][0]
    parameters = calls[0][1]
    assert parameters[3:6] == (
        "capital-increase:1",
        Money.nok("100").amount,
        Money.nok("25").amount,
    )
    assert parameters[13] == "ledger-supported-patterns-2026.1"
    sources = json.loads(str(parameters[14]))
    assert tuple(source["capability"] for source in sources) == expected_capabilities
    assert tuple(source["role"] for source in sources) == (
        "PRIMARY",
        *("CORROBORATING" for _ in expected_capabilities[1:]),
    )


@pytest.mark.parametrize(
    (
        "method_name",
        "command_phase",
        "capital_increase_reference_id",
        "nominal_increase",
        "share_premium",
        "lines",
    ),
    [
        (
            "record_cash_capital_increase_subscription",
            CapitalIncreasePhase.BINDING_SUBSCRIPTION,
            CapitalIncreaseReferenceId("capital-increase:wrong"),
            Money.nok("100"),
            Money.nok("25"),
            (
                LedgerLine("1500", "Receivable", Money.nok("125"), Money.nok("0")),
                LedgerLine("2030", "Unregistered", Money.nok("0"), Money.nok("125")),
            ),
        ),
        (
            "record_cash_capital_increase_subscription",
            CapitalIncreasePhase.BINDING_SUBSCRIPTION,
            CapitalIncreaseReferenceId("capital-increase:1"),
            Money.nok("99"),
            Money.nok("25"),
            (
                LedgerLine("1500", "Receivable", Money.nok("124"), Money.nok("0")),
                LedgerLine("2030", "Unregistered", Money.nok("0"), Money.nok("124")),
            ),
        ),
        (
            "record_cash_capital_increase_subscription",
            CapitalIncreasePhase.BINDING_SUBSCRIPTION,
            CapitalIncreaseReferenceId("capital-increase:1"),
            Money.nok("100"),
            Money.nok("24"),
            (
                LedgerLine("1500", "Receivable", Money.nok("124"), Money.nok("0")),
                LedgerLine("2030", "Unregistered", Money.nok("0"), Money.nok("124")),
            ),
        ),
        (
            "record_cash_capital_increase_subscription",
            CapitalIncreasePhase.RESTRICTED_PAYMENT,
            CapitalIncreaseReferenceId("capital-increase:1"),
            Money.nok("100"),
            Money.nok("25"),
            (
                LedgerLine("1500", "Receivable", Money.nok("125"), Money.nok("0")),
                LedgerLine("2030", "Unregistered", Money.nok("0"), Money.nok("125")),
            ),
        ),
        (
            "record_cash_capital_increase_subscription",
            CapitalIncreasePhase.BINDING_SUBSCRIPTION,
            CapitalIncreaseReferenceId("capital-increase:1"),
            Money.nok("100"),
            Money.nok("25"),
            (
                LedgerLine("1500", "Receivable", Money.nok("124"), Money.nok("0")),
                LedgerLine("2030", "Unregistered", Money.nok("0"), Money.nok("125")),
            ),
        ),
        (
            "record_cash_capital_increase_restricted_payment",
            CapitalIncreasePhase.RESTRICTED_PAYMENT,
            CapitalIncreaseReferenceId("capital-increase:1"),
            Money.nok("100"),
            Money.nok("25"),
            (
                LedgerLine("1921", "Restricted", Money.nok("124"), Money.nok("0")),
                LedgerLine("1500", "Receivable", Money.nok("0"), Money.nok("125")),
            ),
        ),
        (
            "record_cash_capital_increase_registration",
            CapitalIncreasePhase.REGISTERED,
            CapitalIncreaseReferenceId("capital-increase:1"),
            Money.nok("100"),
            Money.nok("25"),
            (
                LedgerLine("2030", "Unregistered", Money.nok("125"), Money.nok("0")),
                LedgerLine("2000", "Capital", Money.nok("0"), Money.nok("100")),
                LedgerLine("2020", "Premium", Money.nok("0"), Money.nok("25")),
            ),
        ),
    ],
)
def test_cash_capital_increase_adapter_rejects_each_binding_mismatch_before_sql(
    method_name: str,
    command_phase: CapitalIncreasePhase,
    capital_increase_reference_id: CapitalIncreaseReferenceId,
    nominal_increase: Money,
    share_premium: Money,
    lines: tuple[LedgerLine, ...],
) -> None:
    session = bound_session()

    async def forbidden_database(*_args: object, **_kwargs: object) -> list[object]:
        raise AssertionError("database must not be called")

    session._database_rows = forbidden_database  # type: ignore[method-assign]
    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            getattr(session, method_name)(
                cash_capital_increase_command(command_phase),
                capital_increase_reference_id=capital_increase_reference_id,
                nominal_increase=nominal_increase,
                share_premium=share_premium,
                memo="Cash capital increase",
                lines=lines,
            )
        )

    assert failure.value.code == "LEDGER_INVALID_INPUT"


@pytest.mark.parametrize(
    (
        "recognition",
        "method_name",
        "function_name",
        "lines",
        "expected_capabilities",
    ),
    [
        (
            CapitalReductionRecognition.DECIDED_NOT_REGISTERED,
            "record_loss_coverage_capital_reduction_decision",
            "record_loss_coverage_capital_reduction_decision_v1",
            (
                LedgerLine("2033", "Unregistered", Money.nok("100"), Money.nok("0")),
                LedgerLine("2080", "Loss", Money.nok("0"), Money.nok("100")),
            ),
            ("CORPORATE_GOVERNANCE", "DOCUMENTS"),
        ),
        (
            registered_capital_reduction_recognition(),
            "record_loss_coverage_capital_reduction_registration",
            "record_loss_coverage_capital_reduction_registration_v1",
            (
                LedgerLine("2000", "Capital", Money.nok("100"), Money.nok("0")),
                LedgerLine("2033", "Unregistered", Money.nok("0"), Money.nok("100")),
            ),
            (
                "CORPORATE_GOVERNANCE",
                "DOCUMENTS",
                "SHAREHOLDER_REGISTER_FILING",
            ),
        ),
        (
            CapitalReductionRecognition.FIRST_RECOGNIZED_AFTER_REGISTRATION,
            "record_loss_coverage_capital_reduction_direct_registration",
            "record_loss_coverage_capital_reduction_direct_registration_v1",
            (
                LedgerLine("2000", "Capital", Money.nok("100"), Money.nok("0")),
                LedgerLine("2080", "Loss", Money.nok("0"), Money.nok("100")),
            ),
            (
                "CORPORATE_GOVERNANCE",
                "DOCUMENTS",
                "SHAREHOLDER_REGISTER_FILING",
            ),
        ),
    ],
)
def test_loss_coverage_capital_reduction_adapter_binds_exact_phase_rpc(
    recognition: CapitalReductionRecognition,
    method_name: str,
    function_name: str,
    lines: tuple[LedgerLine, ...],
    expected_capabilities: tuple[str, ...],
) -> None:
    session = bound_session()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{
            "ledger_entry_id": "40000000-0000-0000-0000-000000000008",
            "company_id": "10000000-0000-0000-0000-000000000001",
            "income_year": 2026,
            "entry_kind": "CAPITAL_REDUCTION",
            "posted_at": datetime(2026, 8, 27, 10, tzinfo=UTC),
            "replayed": False,
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    result = asyncio.run(
        getattr(session, method_name)(
            capital_reduction_command(recognition),
            capital_reduction_reference_id=capital_reduction_reference_id(),
            nominal_reduction=Money.nok("100.00"),
            memo="Loss-coverage capital reduction",
            lines=lines,
        )
    )

    assert result.entry_kind is LedgerEntryKind.CAPITAL_REDUCTION
    assert f"ledger.{function_name}" in calls[0][0]
    parameters = calls[0][1]
    assert parameters[3:5] == (
        "capital-reduction:loss-coverage:1",
        Money.nok("100").amount,
    )
    assert parameters[12] == "ledger-supported-patterns-2026.1"
    sources = json.loads(str(parameters[13]))
    assert tuple(source["capability"] for source in sources) == expected_capabilities
    assert tuple(source["role"] for source in sources) == (
        "PRIMARY",
        *("CORROBORATING" for _ in expected_capabilities[1:]),
    )


@pytest.mark.parametrize(
    (
        "method_name",
        "command_recognition",
        "capital_reduction_reference_value",
        "nominal_reduction",
        "lines",
    ),
    [
        (
            "record_loss_coverage_capital_reduction_decision",
            CapitalReductionRecognition.DECIDED_NOT_REGISTERED,
            "capital-reduction:wrong",
            Money.nok("100"),
            (
                LedgerLine("2033", "Unregistered", Money.nok("100"), Money.nok("0")),
                LedgerLine("2080", "Loss", Money.nok("0"), Money.nok("100")),
            ),
        ),
        (
            "record_loss_coverage_capital_reduction_decision",
            CapitalReductionRecognition.DECIDED_NOT_REGISTERED,
            "capital-reduction:loss-coverage:1",
            Money.nok("99"),
            (
                LedgerLine("2033", "Unregistered", Money.nok("99"), Money.nok("0")),
                LedgerLine("2080", "Loss", Money.nok("0"), Money.nok("99")),
            ),
        ),
        (
            "record_loss_coverage_capital_reduction_decision",
            registered_capital_reduction_recognition(),
            "capital-reduction:loss-coverage:1",
            Money.nok("100"),
            (
                LedgerLine("2033", "Unregistered", Money.nok("100"), Money.nok("0")),
                LedgerLine("2080", "Loss", Money.nok("0"), Money.nok("100")),
            ),
        ),
        (
            "record_loss_coverage_capital_reduction_decision",
            CapitalReductionRecognition.DECIDED_NOT_REGISTERED,
            "capital-reduction:loss-coverage:1",
            Money.nok("100"),
            (
                LedgerLine("2033", "Unregistered", Money.nok("99"), Money.nok("0")),
                LedgerLine("2080", "Loss", Money.nok("0"), Money.nok("100")),
            ),
        ),
        (
            "record_loss_coverage_capital_reduction_registration",
            registered_capital_reduction_recognition(),
            "capital-reduction:loss-coverage:1",
            Money.nok("100"),
            (
                LedgerLine("2000", "Capital", Money.nok("100"), Money.nok("0")),
                LedgerLine("2033", "Unregistered", Money.nok("0"), Money.nok("99")),
            ),
        ),
    ],
)
def test_loss_coverage_capital_reduction_adapter_rejects_binding_mismatch_before_sql(
    method_name: str,
    command_recognition: CapitalReductionRecognition,
    capital_reduction_reference_value: str,
    nominal_reduction: Money,
    lines: tuple[LedgerLine, ...],
) -> None:
    session = bound_session()

    async def forbidden_database(*_args: object, **_kwargs: object) -> list[object]:
        raise AssertionError("database must not be called")

    session._database_rows = forbidden_database  # type: ignore[method-assign]
    reference_type = type(capital_reduction_reference_id())
    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            getattr(session, method_name)(
                capital_reduction_command(command_recognition),
                capital_reduction_reference_id=reference_type(
                    capital_reduction_reference_value
                ),
                nominal_reduction=nominal_reduction,
                memo="Loss-coverage capital reduction",
                lines=lines,
            )
        )

    assert failure.value.code == "LEDGER_INVALID_INPUT"


def test_correction_adapter_binds_original_replacement_and_two_sources() -> None:
    session = bound_session()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{
            "reversal_entry_id": "40000000-0000-0000-0000-000000000005",
            "replacement_entry_id": "40000000-0000-0000-0000-000000000006",
            "company_id": "10000000-0000-0000-0000-000000000001",
            "income_year": 2026,
            "corrected_at": datetime(2026, 8, 27, 10, tzinfo=UTC),
            "replayed": False,
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    result = asyncio.run(
        session.correct_entry(
            correction_command(),
            entry_kind=LedgerEntryKind.ADMINISTRATIVE_COST,
            memo="Wrong documented business category",
            lines=(
                LedgerLine(
                    "6720",
                    "Corrected administrative cost",
                    Money.nok("1250"),
                    Money.nok("0"),
                ),
                LedgerLine(
                    "1920", "Paid from bank", Money.nok("0"), Money.nok("1250")
                ),
            ),
        )
    )

    assert str(result.reversal_entry_id) == "40000000-0000-0000-0000-000000000005"
    assert "ledger.correct_entry_v1" in calls[0][0]
    assert calls[0][1][3] == "40000000-0000-0000-0000-000000000004"
    assert calls[0][1][5] == "ADMINISTRATIVE_COST"
    assert calls[0][1][11] == "CURRENT_COMPANY_YEAR"
    assert [source["capability"] for source in json.loads(str(calls[0][1][13]))] == [
        "DOCUMENTS",
        "BANKING",
    ]


def test_company_year_close_adapter_binds_derived_state_and_evidence() -> None:
    session = bound_session()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{
            "assessment_id": "71000000-0000-0000-0000-000000000007",
            "close_lock_id": "50000000-0000-0000-0000-000000000005",
            "reconstruction_assessment_id": (
                "70000000-0000-0000-0000-000000000007"
            ),
            "company_id": "10000000-0000-0000-0000-000000000001",
            "income_year": 2026,
            "period_end": date(2026, 12, 31),
            "state": "CLOSED",
            "gap_codes": [],
            "evidence_digest": "c" * 64,
            "ledger_state_digest": "d" * 64,
            "recorded_at": datetime(2026, 12, 31, 22, tzinfo=UTC),
            "is_current": True,
            "replayed": False,
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    result = asyncio.run(
        session.record_company_year_close(
            close_company_year_command(),
            evidence=close_company_year_command().evidence,
            state=CompanyYearCloseState.CLOSED,
            gap_codes=(),
        )
    )

    assert result.state is CompanyYearCloseState.CLOSED
    assert "ledger.close_company_year_v1" in calls[0][0]
    assert calls[0][1][3] == date(2026, 12, 31)
    assert calls[0][1][8] == "CLOSED"
    evidence_payload = json.loads(str(calls[0][1][7]))
    assert evidence_payload[0]["issuer"] == "BANKING"
    assert evidence_payload[0]["ledgerStateDigest"] == "d" * 64
    assert [output["kind"] for output in evidence_payload[2]["outputs"]] == [
        kind.value for kind in CompanyYearCloseOutputKind
    ]
    assert all(
        output["economicFactsDigest"] == "e" * 64
        for output in evidence_payload[2]["outputs"]
    )


def test_company_year_close_adapter_checks_the_permanent_replay_first() -> None:
    session = bound_session()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return []

    session._database_rows = database_rows  # type: ignore[method-assign]
    result = asyncio.run(
        session.get_company_year_close_replay(
            close_company_year_command(),
            evidence=close_company_year_command().evidence,
        )
    )

    assert result is None
    assert "ledger.get_company_year_close_replay_v1" in calls[0][0]
    assert calls[0][1][8] == "company-year-close-adapter"


def test_company_year_close_adapter_reads_the_latest_assessment() -> None:
    session = bound_session()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def database_rows(
        query: str, parameters: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        calls.append((query, parameters))
        return [{
            "assessment_id": "71000000-0000-0000-0000-000000000007",
            "close_lock_id": "50000000-0000-0000-0000-000000000005",
            "reconstruction_assessment_id": (
                "70000000-0000-0000-0000-000000000007"
            ),
            "company_id": "10000000-0000-0000-0000-000000000001",
            "income_year": 2026,
            "period_end": date(2026, 12, 31),
            "state": "CLOSED",
            "gap_codes": [],
            "evidence_digest": "c" * 64,
            "ledger_state_digest": "d" * 64,
            "recorded_at": datetime(2026, 12, 31, 22, tzinfo=UTC),
            "is_current": False,
            "replayed": False,
        }]

    session._database_rows = database_rows  # type: ignore[method-assign]
    result = asyncio.run(
        session.get_company_year_close_assessment(
            actor_id=ACTOR_ID,
            company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
            income_year=IncomeYear(2026),
            correlation_id=CorrelationId("company-year-close-query"),
        )
    )

    assert result.state is CompanyYearCloseState.CLOSED
    assert result.is_current is False
    assert str(result.reconstruction_assessment_id) == (
        "70000000-0000-0000-0000-000000000007"
    )
    assert "ledger.get_company_year_close_assessment_v1" in calls[0][0]
    assert calls[0][1] == (
        "10000000-0000-0000-0000-000000000001",
        2026,
        "20000000-0000-0000-0000-000000000002",
    )


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
        (
            "ledger_company_year_close_evidence_invalid",
            "LEDGER_COMPANY_YEAR_CLOSE_EVIDENCE_INVALID",
        ),
        (
            "ledger_company_year_close_reconstruction_stale",
            "LEDGER_COMPANY_YEAR_CLOSE_RECONSTRUCTION_STALE",
        ),
        ("ledger_reconstruction_stale", "LEDGER_RECONSTRUCTION_STALE"),
        (
            "ledger_reconstruction_source_evidence_invalid",
            "LEDGER_RECONSTRUCTION_SOURCE_EVIDENCE_INVALID",
        ),
        (
            "ledger_correction_original_kind_unsupported",
            "LEDGER_CORRECTION_ORIGINAL_KIND_UNSUPPORTED",
        ),
        (
            "ledger_prior_year_correction_policy_unresolved",
            "LEDGER_PRIOR_YEAR_CORRECTION_POLICY_UNRESOLVED",
        ),
        ("ledger_bank_loan_already_exists", "LEDGER_BANK_LOAN_ALREADY_EXISTS"),
        ("ledger_bank_loan_event_invalid", "LEDGER_BANK_LOAN_EVENT_INVALID"),
        (
            "ledger_opening_loan_anchor_missing",
            "LEDGER_OPENING_LOAN_ANCHOR_MISSING",
        ),
        (
            "ledger_bank_loan_principal_exceeded",
            "LEDGER_BANK_LOAN_PRINCIPAL_EXCEEDED",
        ),
        (
            "ledger_cash_capital_increase_phase_invalid",
            "LEDGER_CASH_CAPITAL_INCREASE_PHASE_INVALID",
        ),
        (
            "ledger_cash_capital_increase_phase_missing",
            "LEDGER_CASH_CAPITAL_INCREASE_PHASE_MISSING",
        ),
        (
            "ledger_cash_capital_increase_amount_mismatch",
            "LEDGER_CASH_CAPITAL_INCREASE_AMOUNT_MISMATCH",
        ),
        (
            "ledger_cash_capital_increase_phase_already_recorded",
            "LEDGER_CASH_CAPITAL_INCREASE_PHASE_ALREADY_RECORDED",
        ),
        (
            "ledger_opening_capital_increase_anchor_missing",
            "LEDGER_OPENING_CAPITAL_INCREASE_ANCHOR_MISSING",
        ),
        (
            "ledger_loss_coverage_capital_reduction_phase_invalid",
            "LEDGER_LOSS_COVERAGE_CAPITAL_REDUCTION_PHASE_INVALID",
        ),
        (
            "ledger_loss_coverage_capital_reduction_amount_mismatch",
            "LEDGER_LOSS_COVERAGE_CAPITAL_REDUCTION_AMOUNT_MISMATCH",
        ),
        (
            "ledger_loss_coverage_capital_reduction_phase_already_recorded",
            "LEDGER_LOSS_COVERAGE_CAPITAL_REDUCTION_PHASE_ALREADY_RECORDED",
        ),
        (
            "ledger_opening_capital_reduction_anchor_missing",
            "LEDGER_OPENING_CAPITAL_REDUCTION_ANCHOR_MISSING",
        ),
        ("ledger_opening_balance_invalid", "LEDGER_OPENING_BALANCE_INVALID"),
        ("ledger_opening_source_overlap", "LEDGER_OPENING_SOURCE_OVERLAP"),
        ("ledger_entry_already_corrected", "LEDGER_ENTRY_ALREADY_CORRECTED"),
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


def test_entry_projection_recognizes_technical_correction_reversal() -> None:
    entry = bound_session()._entry_view({
        "entryId": "40000000-0000-0000-0000-000000000005",
        "companyId": "10000000-0000-0000-0000-000000000001",
        "incomeYear": 2026,
        "entryKind": "CORRECTION_REVERSAL",
        "memo": "Full reversal: documented category was wrong",
        "lines": [
            {
                "account": "7795",
                "description": "Administration cost",
                "debit": "0.00",
                "credit": "500.00",
                "currency": "NOK",
            },
            {
                "account": "1920",
                "description": "Bank",
                "debit": "500.00",
                "credit": "0.00",
                "currency": "NOK",
            },
        ],
        "riskFlags": [],
        "postedBy": str(ACTOR_ID.subject),
        "postedAt": "2026-08-27T10:00:00Z",
    })

    assert entry.entry_kind is LedgerEntryKind.CORRECTION_REVERSAL


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
