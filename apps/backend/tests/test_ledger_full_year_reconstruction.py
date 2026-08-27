from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from talli_backend.modules.ledger.public import (
    LedgerError,
    LedgerSourceRecordId,
    ReconstructionAssessment,
    ReconstructionAssessmentId,
    ReconstructionEvidence,
    ReconstructionEvidenceIssuer,
    ReconstructionEvidenceKind,
    ReconstructionEvidenceStatus,
    ReconstructionState,
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
            recorded_at=Timestamp(datetime(2026, 8, 27, 10, tzinfo=UTC)),
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
        gap_code="DOCUMENT_COVERAGE_UNKNOWN",
    )

    result = asyncio.run(
        LedgerService(persistence).record_reconstruction_assessment(
            command(tuple(evidence))
        )
    )

    assert result.state is ReconstructionState.BLOCKED
    assert persistence.calls[0]["gap_codes"] == ("DOCUMENT_COVERAGE_UNKNOWN",)


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
