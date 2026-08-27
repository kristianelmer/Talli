from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from talli_backend.modules.ledger.public import (
    LedgerError,
    LedgerEntryKind,
    LedgerEntryId,
    LedgerFactReference,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    OpeningBalanceCategory,
    OpeningBalanceComponent,
    PostedLedgerEntry,
    ReconstructionAssessment,
    ReconstructionAssessmentId,
    ReconstructionEvidence,
    ReconstructionEvidenceIssuer,
    ReconstructionEvidenceKind,
    ReconstructionEvidenceStatus,
    ReconstructionGapCode,
    ReconstructionState,
    RebuildCompanyYearOpeningCommand,
    RecordReconstructionAssessmentCommand,
)
from talli_backend.modules.ledger.service import LedgerService
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    ErrorCategory,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    Money,
    Timestamp,
    UserId,
)


COMPANY_ID = CompanyId("10000000-0000-0000-0000-000000000001")
ACTOR_ID = ActorId(
    kind=ActorKind.USER,
    subject=UserId("20000000-0000-0000-0000-000000000002"),
)
INCOME_YEAR = IncomeYear(2026)
AS_OF = LocalDate(date(2026, 8, 27))


class ReconstructionPersistenceStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def record_reconstruction_assessment(
        self,
        command: RecordReconstructionAssessmentCommand,
        **result: object,
    ) -> ReconstructionAssessment:
        self.calls.append({"command": command, **result})
        return ReconstructionAssessment(
            assessment_id=ReconstructionAssessmentId(
                "40000000-0000-0000-0000-000000000004"
            ),
            company_id=command.company_id,
            income_year=command.income_year,
            as_of=command.as_of,
            state=result["state"],
            gap_codes=result["gap_codes"],
            evidence_digest="a" * 64,
            ledger_state_digest="b" * 64,
            recorded_at=Timestamp(datetime(2026, 8, 27, 10, tzinfo=UTC)),
            replayed=False,
        )

    async def rebuild_company_year_opening(
        self,
        command: RebuildCompanyYearOpeningCommand,
        *,
        lines: tuple[object, ...],
        entry_sources: tuple[LedgerFactReference, ...],
    ) -> PostedLedgerEntry:
        self.calls.append(
            {"command": command, "lines": lines, "entry_sources": entry_sources}
        )
        return PostedLedgerEntry(
            entry_id=LedgerEntryId("50000000-0000-0000-0000-000000000005"),
            company_id=command.company_id,
            income_year=command.income_year,
            entry_kind=LedgerEntryKind.OPENING_BALANCE,
            posted_at=Timestamp(datetime(2026, 8, 27, 10, tzinfo=UTC)),
            replayed=False,
        )


def command(evidence: tuple[ReconstructionEvidence, ...]) -> RecordReconstructionAssessmentCommand:
    return RecordReconstructionAssessmentCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("ledger-reconstruction-test"),
        idempotency_key=IdempotencyKey("reconstruction-assessment-2026-08-27"),
        income_year=INCOME_YEAR,
        as_of=AS_OF,
        evidence=evidence,
    )


def complete_evidence() -> tuple[ReconstructionEvidence, ...]:
    requirements = (
        (ReconstructionEvidenceKind.PRIOR_CLOSING_OPENING, ReconstructionEvidenceIssuer.LEDGER),
        (ReconstructionEvidenceKind.BANK_MOVEMENTS, ReconstructionEvidenceIssuer.BANKING),
        (ReconstructionEvidenceKind.BANK_RECONCILIATION, ReconstructionEvidenceIssuer.BANKING),
        (ReconstructionEvidenceKind.INVESTMENTS, ReconstructionEvidenceIssuer.INVESTMENTS),
        (
            ReconstructionEvidenceKind.SHAREHOLDERS,
            ReconstructionEvidenceIssuer.SHAREHOLDER_REGISTER_FILING,
        ),
        (ReconstructionEvidenceKind.LOANS, ReconstructionEvidenceIssuer.BANKING),
        (
            ReconstructionEvidenceKind.LOANS,
            ReconstructionEvidenceIssuer.CORPORATE_GOVERNANCE,
        ),
        (
            ReconstructionEvidenceKind.EQUITY,
            ReconstructionEvidenceIssuer.CORPORATE_GOVERNANCE,
        ),
        (
            ReconstructionEvidenceKind.EQUITY,
            ReconstructionEvidenceIssuer.SHAREHOLDER_REGISTER_FILING,
        ),
        (
            ReconstructionEvidenceKind.TAX_HISTORY,
            ReconstructionEvidenceIssuer.COMPANY_TAX_FILING,
        ),
        (
            ReconstructionEvidenceKind.CURRENT_YEAR_ACTIVITY,
            ReconstructionEvidenceIssuer.LEDGER,
        ),
        (ReconstructionEvidenceKind.DOCUMENTS, ReconstructionEvidenceIssuer.DOCUMENTS),
        (
            ReconstructionEvidenceKind.UNSUPPORTED_ACTIVITY_CHECK,
            ReconstructionEvidenceIssuer.COMPANY_ACCESS,
        ),
    )
    rows: list[ReconstructionEvidence] = []
    for index, (kind, issuer) in enumerate(requirements):
        coverage = kind in {
            ReconstructionEvidenceKind.BANK_MOVEMENTS,
            ReconstructionEvidenceKind.CURRENT_YEAR_ACTIVITY,
        }
        rows.append(
            ReconstructionEvidence(
                kind=kind,
                confirmation=ReconstructionEvidenceStatus.CONFIRMED,
                issuer=issuer,
                source_record_id=LedgerSourceRecordId(f"fact:{index}:{kind.value}"),
                fact_sha256=f"{index:064x}",
                coverage_from=LocalDate(date(2026, 1, 1)) if coverage else None,
                coverage_through=AS_OF if coverage else None,
            )
        )
    return tuple(reversed(rows))


def test_complete_january_to_date_evidence_is_canonicalized_and_ready() -> None:
    persistence = ReconstructionPersistenceStub()

    result = asyncio.run(
        LedgerService(persistence).record_reconstruction_assessment(
            command(complete_evidence())
        )
    )

    assert result.state is ReconstructionState.READY
    assert persistence.calls[0]["gap_codes"] == ()
    canonical = persistence.calls[0]["evidence"]
    assert len(canonical) == 13
    assert [item.issuer for item in canonical if item.kind is ReconstructionEvidenceKind.LOANS] == [
        ReconstructionEvidenceIssuer.BANKING,
        ReconstructionEvidenceIssuer.CORPORATE_GOVERNANCE,
    ]


def test_unknown_source_fact_records_a_stable_gap_and_blocks_readiness() -> None:
    persistence = ReconstructionPersistenceStub()
    evidence = list(complete_evidence())
    index = next(
        index
        for index, item in enumerate(evidence)
        if item.kind is ReconstructionEvidenceKind.DOCUMENTS
    )
    item = evidence[index]
    evidence[index] = ReconstructionEvidence(
        kind=item.kind,
        confirmation=ReconstructionEvidenceStatus.UNKNOWN,
        issuer=item.issuer,
        source_record_id=item.source_record_id,
        fact_sha256=item.fact_sha256,
        gap_code=ReconstructionGapCode.DOCUMENTS_INCOMPLETE,
    )

    result = asyncio.run(
        LedgerService(persistence).record_reconstruction_assessment(
            command(tuple(evidence))
        )
    )

    assert result.state is ReconstructionState.BLOCKED
    assert persistence.calls[0]["gap_codes"] == (
        ReconstructionGapCode.DOCUMENTS_INCOMPLETE,
    )


def test_missing_evidence_kind_fails_closed_without_persistence() -> None:
    persistence = ReconstructionPersistenceStub()

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).record_reconstruction_assessment(
                command(complete_evidence()[:-1])
            )
        )

    assert failure.value.code == "LEDGER_RECONSTRUCTION_EVIDENCE_INCOMPLETE"
    assert failure.value.category is ErrorCategory.PRECONDITION_FAILED
    assert persistence.calls == []


def test_bank_and_activity_coverage_must_start_on_january_first_and_reach_cutoff() -> None:
    persistence = ReconstructionPersistenceStub()
    evidence = list(complete_evidence())
    index = next(
        index
        for index, item in enumerate(evidence)
        if item.kind is ReconstructionEvidenceKind.BANK_MOVEMENTS
    )
    item = evidence[index]
    evidence[index] = ReconstructionEvidence(
        kind=item.kind,
        confirmation=item.confirmation,
        issuer=item.issuer,
        source_record_id=item.source_record_id,
        fact_sha256=item.fact_sha256,
        coverage_from=LocalDate(date(2026, 2, 1)),
        coverage_through=AS_OF,
    )

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).record_reconstruction_assessment(
                command(tuple(evidence))
            )
        )

    assert failure.value.code == "LEDGER_RECONSTRUCTION_COVERAGE_INVALID"
    assert persistence.calls == []


def opening_component(
    category: OpeningBalanceCategory,
    reference_id: str,
    amount: str,
    primary_capability: LedgerSourceCapability,
    digest_character: str,
) -> OpeningBalanceComponent:
    return OpeningBalanceComponent(
        category=category,
        reference_id=LedgerSourceRecordId(reference_id),
        amount=Money.nok(amount),
        primary_source=LedgerFactReference(
            capability=primary_capability,
            record_id=LedgerSourceRecordId(f"fact:{reference_id}"),
            revision=1,
            fact_sha256=digest_character * 64,
        ),
        corroborating_sources=(
            LedgerFactReference(
                capability=LedgerSourceCapability.DOCUMENTS,
                record_id=LedgerSourceRecordId(f"document:{reference_id}"),
                revision=1,
                fact_sha256=digest_character.upper().lower() * 64,
            ),
        ),
    )


def opening_position_command() -> RebuildCompanyYearOpeningCommand:
    return RebuildCompanyYearOpeningCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("ledger-opening-position-test"),
        idempotency_key=IdempotencyKey("opening-position-2026"),
        income_year=INCOME_YEAR,
        opening_date=LocalDate(date(2026, 1, 1)),
        prior_closing_source=LedgerFactReference(
            capability=LedgerSourceCapability.LEDGER,
            record_id=LedgerSourceRecordId("prior-close:2025"),
            revision=1,
            fact_sha256="0" * 64,
        ),
        components=(
            opening_component(
                OpeningBalanceCategory.REGISTERED_SHARE_CAPITAL,
                "share-capital",
                "30000.00",
                LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING,
                "1",
            ),
            opening_component(
                OpeningBalanceCategory.BANK_LOAN_PAYABLE,
                "bank-loan:prior-year:2",
                "25000.00",
                LedgerSourceCapability.BANKING,
                "2",
            ),
            opening_component(
                OpeningBalanceCategory.BANK,
                "bank-account:1",
                "105000.00",
                LedgerSourceCapability.BANKING,
                "3",
            ),
            opening_component(
                OpeningBalanceCategory.BANK_LOAN_PAYABLE,
                "bank-loan:prior-year:1",
                "50000.00",
                LedgerSourceCapability.BANKING,
                "4",
            ),
        ),
    )


def test_complete_opening_is_canonical_balanced_and_account_free() -> None:
    persistence = ReconstructionPersistenceStub()

    result = asyncio.run(
        LedgerService(persistence).rebuild_company_year_opening(
            opening_position_command()
        )
    )

    assert result.entry_kind is LedgerEntryKind.OPENING_BALANCE
    call = persistence.calls[0]
    canonical = call["command"]
    assert isinstance(canonical, RebuildCompanyYearOpeningCommand)
    assert [component.category for component in canonical.components] == [
        OpeningBalanceCategory.BANK,
        OpeningBalanceCategory.BANK_LOAN_PAYABLE,
        OpeningBalanceCategory.BANK_LOAN_PAYABLE,
        OpeningBalanceCategory.REGISTERED_SHARE_CAPITAL,
    ]
    lines = call["lines"]
    assert [(line.account, line.debit.amount, line.credit.amount) for line in lines] == [
        ("1920", Money.nok("105000.00").amount, Money.nok("0").amount),
        ("2220", Money.nok("0").amount, Money.nok("50000.00").amount),
        ("2220", Money.nok("0").amount, Money.nok("25000.00").amount),
        ("2000", Money.nok("0").amount, Money.nok("30000.00").amount),
    ]
    assert "account" not in OpeningBalanceComponent.__dataclass_fields__
    assert "debit" not in OpeningBalanceComponent.__dataclass_fields__
    assert "credit" not in OpeningBalanceComponent.__dataclass_fields__
    assert "lines" not in RebuildCompanyYearOpeningCommand.__dataclass_fields__


def test_opening_source_overlap_fails_before_persistence() -> None:
    persistence = ReconstructionPersistenceStub()
    command = opening_position_command()
    duplicated = replace(
        command.components[1],
        primary_source=command.components[0].primary_source,
    )
    command = replace(command, components=(command.components[0], duplicated))

    with pytest.raises(LedgerError) as failure:
        asyncio.run(LedgerService(persistence).rebuild_company_year_opening(command))

    assert failure.value.code in {
        "LEDGER_OPENING_EVIDENCE_INVALID",
        "LEDGER_OPENING_SOURCE_OVERLAP",
    }
    assert persistence.calls == []
