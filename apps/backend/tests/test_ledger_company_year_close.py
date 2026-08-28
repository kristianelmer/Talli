from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from talli_backend.modules.ledger.public import (
    CloseCompanyYearCommand,
    CompanyYearCloseAssessment,
    CompanyYearCloseAssessmentId,
    CompanyYearCloseEvidence,
    CompanyYearCloseEvidenceKind,
    CompanyYearCloseGapCode,
    CompanyYearCloseLockId,
    CompanyYearCloseOutputKind,
    CompanyYearCloseOutputReference,
    CompanyYearCloseState,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    ReconstructionAssessment,
    ReconstructionAssessmentId,
    ReconstructionEvidenceStatus,
    ReconstructionGapCode,
    ReconstructionState,
)
from talli_backend.modules.ledger.service import LedgerService
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
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
RECONSTRUCTION_ID = ReconstructionAssessmentId(
    "70000000-0000-0000-0000-000000000007"
)
NOW = Timestamp(datetime(2026, 12, 31, 22, tzinfo=UTC))
LEDGER_STATE_DIGEST = "c" * 64
ECONOMIC_FACTS_DIGEST = "e" * 64
SOURCE_EVIDENCE_DIGEST = "a" * 64
REQUIRED_OUTPUT_KINDS = tuple(CompanyYearCloseOutputKind)


def reconstruction(
    *,
    state: ReconstructionState = ReconstructionState.READY,
    gaps: tuple[ReconstructionGapCode, ...] = (),
    as_of: date = date(2026, 12, 31),
) -> ReconstructionAssessment:
    return ReconstructionAssessment(
        assessment_id=RECONSTRUCTION_ID,
        company_id=COMPANY_ID,
        income_year=IncomeYear(2026),
        as_of=LocalDate(as_of),
        state=state,
        gap_codes=gaps,
        evidence_digest="a" * 64,
        ledger_state_digest=LEDGER_STATE_DIGEST,
        economic_facts_digest=ECONOMIC_FACTS_DIGEST,
        economic_fact_count=19,
        source_evidence_digest=SOURCE_EVIDENCE_DIGEST,
        source_evidence_count=13,
        recorded_at=NOW,
        replayed=False,
    )


def evidence(
    kind: CompanyYearCloseEvidenceKind,
    issuer: LedgerSourceCapability,
    *,
    status: ReconstructionEvidenceStatus = ReconstructionEvidenceStatus.CONFIRMED,
    gap_code: CompanyYearCloseGapCode | None = None,
) -> CompanyYearCloseEvidence:
    outputs = (
        tuple(
            CompanyYearCloseOutputReference(
                kind=output_kind,
                source_record_id=LedgerSourceRecordId(
                    f"close-output:{output_kind.value.lower()}"
                ),
                revision=1,
                fact_sha256=(output_kind.value.encode().hex().ljust(64, "0")[:64]),
                economic_facts_digest=ECONOMIC_FACTS_DIGEST,
            )
            for output_kind in REQUIRED_OUTPUT_KINDS
        )
        if kind is CompanyYearCloseEvidenceKind.REPORTING_RECONCILED
        else ()
    )
    return CompanyYearCloseEvidence(
        kind=kind,
        issuer=issuer,
        source_record_id=LedgerSourceRecordId(f"close:{kind.value.lower()}"),
        revision=1,
        fact_sha256=kind.value.encode().hex().ljust(64, "0")[:64],
        ledger_state_digest=LEDGER_STATE_DIGEST,
        coverage_through=LocalDate(date(2026, 12, 31)),
        confirmation=status,
        gap_code=gap_code,
        outputs=outputs,
    )


def complete_evidence() -> tuple[CompanyYearCloseEvidence, ...]:
    return (
        evidence(
            CompanyYearCloseEvidenceKind.BANK_ROWS_RESOLVED,
            LedgerSourceCapability.BANKING,
        ),
        evidence(
            CompanyYearCloseEvidenceKind.MATERIAL_BALANCES_DOCUMENTED,
            LedgerSourceCapability.DOCUMENTS,
        ),
        evidence(
            CompanyYearCloseEvidenceKind.REPORTING_RECONCILED,
            LedgerSourceCapability.LEDGER,
        ),
    )


def command(
    *,
    close_evidence: tuple[CompanyYearCloseEvidence, ...] | None = None,
    period_end: date = date(2026, 12, 31),
) -> CloseCompanyYearCommand:
    return CloseCompanyYearCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("company-year-close-test"),
        idempotency_key=IdempotencyKey("company-year-close-test-0001"),
        income_year=IncomeYear(2026),
        period_end=LocalDate(period_end),
        reason="Documented company-year close",
        reconstruction_assessment_id=RECONSTRUCTION_ID,
        reconstruction_evidence_digest="a" * 64,
        evidence=complete_evidence() if close_evidence is None else close_evidence,
    )


class ClosePersistenceStub:
    def __init__(self, current: ReconstructionAssessment) -> None:
        self.current = current
        self.recorded: list[dict[str, object]] = []
        self.replay: CompanyYearCloseAssessment | None = None
        self.replay_calls = 0
        self.reconstruction_calls = 0

    async def get_company_year_close_replay(
        self,
        _command: CloseCompanyYearCommand,
        **_request: object,
    ) -> CompanyYearCloseAssessment | None:
        self.replay_calls += 1
        return self.replay

    async def get_reconstruction_assessment(self, **_query: object) -> ReconstructionAssessment:
        self.reconstruction_calls += 1
        return self.current

    async def record_company_year_close(
        self,
        close_command: CloseCompanyYearCommand,
        **derived: object,
    ) -> CompanyYearCloseAssessment:
        self.recorded.append({"command": close_command, **derived})
        state = derived["state"]
        return CompanyYearCloseAssessment(
            assessment_id=CompanyYearCloseAssessmentId(
                "71000000-0000-0000-0000-000000000007"
            ),
            close_lock_id=(
                CompanyYearCloseLockId("50000000-0000-0000-0000-000000000005")
                if state is CompanyYearCloseState.CLOSED
                else None
            ),
            reconstruction_assessment_id=close_command.reconstruction_assessment_id,
            company_id=close_command.company_id,
            income_year=close_command.income_year,
            period_end=close_command.period_end,
            state=state,
            gap_codes=derived["gap_codes"],
            evidence_digest="b" * 64,
            ledger_state_digest="c" * 64,
            recorded_at=NOW,
            is_current=True,
            replayed=False,
        )


def test_complete_close_facts_create_the_only_closed_outcome() -> None:
    persistence = ClosePersistenceStub(reconstruction())

    result = asyncio.run(LedgerService(persistence).close_company_year(command()))

    assert result.state is CompanyYearCloseState.CLOSED
    assert result.close_lock_id is not None
    assert persistence.recorded[0]["gap_codes"] == ()
    forbidden = {"source_complete", "bank_reconciled", "account", "lines"}
    assert not (set(CloseCompanyYearCommand.__dataclass_fields__) & forbidden)


def test_missing_close_fact_is_persisted_as_blocked_without_a_lock() -> None:
    persistence = ClosePersistenceStub(reconstruction())

    result = asyncio.run(
        LedgerService(persistence).close_company_year(
            command(close_evidence=complete_evidence()[:-1])
        )
    )

    assert result.state is CompanyYearCloseState.BLOCKED
    assert result.close_lock_id is None
    assert result.gap_codes == (CompanyYearCloseGapCode.CHECK_EVIDENCE_INCOMPLETE,)


def test_duplicate_close_fact_is_rejected_before_persistence() -> None:
    facts = complete_evidence()
    persistence = ClosePersistenceStub(reconstruction())

    with pytest.raises(Exception) as failure:
        asyncio.run(
            LedgerService(persistence).close_company_year(
                command(close_evidence=(*facts, facts[0]))
            )
        )

    assert getattr(failure.value, "code", None) == (
        "LEDGER_COMPANY_YEAR_CLOSE_EVIDENCE_INVALID"
    )
    assert persistence.recorded == []


def test_mismatched_source_gap_is_rejected_before_persistence() -> None:
    facts = list(complete_evidence())
    facts[0] = replace(
        facts[0],
        confirmation=ReconstructionEvidenceStatus.GAP,
        gap_code=CompanyYearCloseGapCode.REPORTING_NOT_RECONCILED,
    )
    persistence = ClosePersistenceStub(reconstruction())

    with pytest.raises(Exception) as failure:
        asyncio.run(
            LedgerService(persistence).close_company_year(
                command(close_evidence=tuple(facts))
            )
        )

    assert getattr(failure.value, "code", None) == (
        "LEDGER_COMPANY_YEAR_CLOSE_EVIDENCE_INVALID"
    )
    assert persistence.recorded == []


def test_reporting_reconciliation_requires_every_stable_output_reference() -> None:
    facts = list(complete_evidence())
    facts[2] = replace(facts[2], outputs=facts[2].outputs[:-1])
    persistence = ClosePersistenceStub(reconstruction())

    with pytest.raises(Exception) as failure:
        asyncio.run(
            LedgerService(persistence).close_company_year(
                command(close_evidence=tuple(facts))
            )
        )

    assert getattr(failure.value, "code", None) == (
        "LEDGER_COMPANY_YEAR_CLOSE_EVIDENCE_INVALID"
    )
    assert persistence.recorded == []


def test_reporting_outputs_must_bind_the_current_economic_fact_set() -> None:
    facts = list(complete_evidence())
    reporting = facts[2]
    facts[2] = replace(
        reporting,
        outputs=(
            replace(reporting.outputs[0], economic_facts_digest="f" * 64),
            *reporting.outputs[1:],
        ),
    )
    persistence = ClosePersistenceStub(reconstruction())

    with pytest.raises(Exception) as failure:
        asyncio.run(
            LedgerService(persistence).close_company_year(
                command(close_evidence=tuple(facts))
            )
        )

    assert getattr(failure.value, "code", None) == (
        "LEDGER_COMPANY_YEAR_CLOSE_RECONSTRUCTION_STALE"
    )
    assert persistence.recorded == []


def test_close_rejects_a_reconstruction_without_revisioned_source_evidence() -> None:
    current = replace(
        reconstruction(),
        source_evidence_digest=None,
        source_evidence_count=None,
    )
    persistence = ClosePersistenceStub(current)

    with pytest.raises(Exception) as failure:
        asyncio.run(
            LedgerService(persistence).close_company_year(
                command(close_evidence=complete_evidence())
            )
        )

    assert getattr(failure.value, "code", None) == (
        "LEDGER_COMPANY_YEAR_CLOSE_RECONSTRUCTION_STALE"
    )
    assert persistence.recorded == []


def test_close_facts_must_share_one_ledger_state_digest() -> None:
    facts = list(complete_evidence())
    facts[0] = replace(facts[0], ledger_state_digest="d" * 64)
    persistence = ClosePersistenceStub(reconstruction())

    with pytest.raises(Exception) as failure:
        asyncio.run(
            LedgerService(persistence).close_company_year(
                command(close_evidence=tuple(facts))
            )
        )

    assert getattr(failure.value, "code", None) == (
        "LEDGER_COMPANY_YEAR_CLOSE_EVIDENCE_INVALID"
    )
    assert persistence.recorded == []


@pytest.mark.parametrize("reconstruction_digest", [None, "d" * 64])
def test_close_facts_must_match_the_reconstructed_ledger_state(
    reconstruction_digest: str | None,
) -> None:
    persistence = ClosePersistenceStub(
        replace(reconstruction(), ledger_state_digest=reconstruction_digest)
    )

    with pytest.raises(Exception) as failure:
        asyncio.run(LedgerService(persistence).close_company_year(command()))

    assert getattr(failure.value, "code", None) == (
        "LEDGER_COMPANY_YEAR_CLOSE_RECONSTRUCTION_STALE"
    )
    assert persistence.recorded == []


def test_exact_committed_replay_precedes_mutable_reconstruction_freshness() -> None:
    persistence = ClosePersistenceStub(
        replace(reconstruction(), assessment_id=ReconstructionAssessmentId(
            "70000000-0000-0000-0000-000000000099"
        ))
    )
    persistence.replay = CompanyYearCloseAssessment(
        assessment_id=CompanyYearCloseAssessmentId(
            "71000000-0000-0000-0000-000000000007"
        ),
        close_lock_id=CompanyYearCloseLockId(
            "50000000-0000-0000-0000-000000000005"
        ),
        reconstruction_assessment_id=RECONSTRUCTION_ID,
        company_id=COMPANY_ID,
        income_year=IncomeYear(2026),
        period_end=LocalDate(date(2026, 12, 31)),
        state=CompanyYearCloseState.CLOSED,
        gap_codes=(),
        evidence_digest="b" * 64,
        ledger_state_digest=LEDGER_STATE_DIGEST,
        recorded_at=NOW,
        is_current=False,
        replayed=True,
    )

    result = asyncio.run(LedgerService(persistence).close_company_year(command()))

    assert result.assessment_id == persistence.replay.assessment_id
    assert result.replayed is True
    assert result.is_current is False
    assert persistence.replay_calls == 1
    assert persistence.reconstruction_calls == 0
    assert persistence.recorded == []


@pytest.mark.parametrize(
    ("index", "gap"),
    [
        (0, CompanyYearCloseGapCode.UNRESOLVED_BANK_ROW),
        (1, CompanyYearCloseGapCode.MATERIAL_BALANCE_UNDOCUMENTED),
        (2, CompanyYearCloseGapCode.REPORTING_NOT_RECONCILED),
    ],
)
def test_unconfirmed_close_fact_returns_its_stable_block(
    index: int, gap: CompanyYearCloseGapCode
) -> None:
    facts = list(complete_evidence())
    facts[index] = replace(
        facts[index],
        confirmation=ReconstructionEvidenceStatus.GAP,
        gap_code=gap,
        outputs=(),
    )
    persistence = ClosePersistenceStub(reconstruction())

    result = asyncio.run(
        LedgerService(persistence).close_company_year(
            command(close_evidence=tuple(facts))
        )
    )

    assert result.gap_codes == (gap,)


def test_partial_period_is_truthfully_blocked_until_effective_dates_are_migrated() -> None:
    persistence = ClosePersistenceStub(reconstruction(as_of=date(2026, 6, 30)))
    period_evidence = tuple(
        replace(item, coverage_through=LocalDate(date(2026, 6, 30)))
        for item in complete_evidence()
    )

    result = asyncio.run(
        LedgerService(persistence).close_company_year(
            command(
                period_end=date(2026, 6, 30),
                close_evidence=period_evidence,
            )
        )
    )

    assert result.state is CompanyYearCloseState.BLOCKED
    assert result.gap_codes == (CompanyYearCloseGapCode.PERIOD_END_UNSUPPORTED,)


def test_close_fact_coverage_must_match_the_period_end_exactly() -> None:
    facts = list(complete_evidence())
    facts[0] = replace(facts[0], coverage_through=LocalDate(date(2027, 1, 1)))
    persistence = ClosePersistenceStub(reconstruction())

    result = asyncio.run(
        LedgerService(persistence).close_company_year(
            command(close_evidence=tuple(facts))
        )
    )

    assert result.state is CompanyYearCloseState.BLOCKED
    assert result.gap_codes == (CompanyYearCloseGapCode.CHECK_EVIDENCE_INCOMPLETE,)


def test_blocked_reconstruction_prevents_a_completion_claim() -> None:
    persistence = ClosePersistenceStub(
        reconstruction(
            state=ReconstructionState.BLOCKED,
            gaps=(ReconstructionGapCode.BANK_NOT_RECONCILED,),
        )
    )

    result = asyncio.run(LedgerService(persistence).close_company_year(command()))

    assert result.state is CompanyYearCloseState.BLOCKED
    assert result.gap_codes == (
        CompanyYearCloseGapCode.SOURCE_INCOMPLETE,
        CompanyYearCloseGapCode.BANK_NOT_RECONCILED,
    )


def test_unsupported_reconstruction_fact_is_preserved_as_a_close_block() -> None:
    persistence = ClosePersistenceStub(
        reconstruction(
            state=ReconstructionState.BLOCKED,
            gaps=(ReconstructionGapCode.UNSUPPORTED_ACTIVITY_FOUND,),
        )
    )

    result = asyncio.run(LedgerService(persistence).close_company_year(command()))

    assert result.gap_codes == (
        CompanyYearCloseGapCode.SOURCE_INCOMPLETE,
        CompanyYearCloseGapCode.UNSUPPORTED_TRANSACTION,
    )


def test_stale_reconstruction_reference_never_reaches_close_persistence() -> None:
    persistence = ClosePersistenceStub(reconstruction())
    stale = replace(command(), reconstruction_evidence_digest="f" * 64)

    with pytest.raises(Exception) as failure:
        asyncio.run(LedgerService(persistence).close_company_year(stale))

    assert getattr(failure.value, "code", None) == (
        "LEDGER_COMPANY_YEAR_CLOSE_RECONSTRUCTION_STALE"
    )
    assert persistence.recorded == []
