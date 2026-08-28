from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from talli_backend.modules.ledger.public import (
    BankLoanMaturity,
    BankLoanReferenceId,
    CapitalIncreasePhase,
    CapitalIncreaseReferenceId,
    CapitalReductionRecognition,
    CapitalReductionReferenceId,
    DividendDecisionReferenceId,
    InvestmentClassification,
    LedgerEntryId,
    LedgerEntryKind,
    LedgerError,
    LedgerFactReference,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    OpeningBalanceCategory,
    OpeningBalanceComponent,
    OpeningBankLoanComponent,
    OpeningCapitalIncreaseComponent,
    OpeningCapitalReductionComponent,
    OpeningDividendPayableComponent,
    OpeningDividendReceivableComponent,
    OpeningInvestmentComponent,
    OpeningPositionMode,
    PostedLedgerEntry,
    RebuildCompanyYearOpeningCommand,
    ReconstructionAssessment,
    ReconstructionAssessmentId,
    ReconstructionEvidence,
    ReconstructionEvidenceIssuer,
    ReconstructionEvidenceKind,
    ReconstructionEvidenceStatus,
    ReconstructionGapCode,
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
        components: tuple[object, ...],
        lines: tuple[object, ...],
        entry_sources: tuple[LedgerFactReference, ...],
    ) -> PostedLedgerEntry:
        self.calls.append(
            {
                "command": command,
                "components": components,
                "lines": lines,
                "entry_sources": entry_sources,
            }
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
        economic_fact_entry_ids=(
            LedgerEntryId("50000000-0000-0000-0000-000000000006"),
            LedgerEntryId("50000000-0000-0000-0000-000000000005"),
        ),
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
        rows.append(
            ReconstructionEvidence(
                kind=kind,
                confirmation=ReconstructionEvidenceStatus.CONFIRMED,
                issuer=issuer,
                source_record_id=LedgerSourceRecordId(f"fact:{index}:{kind.value}"),
                source_revision=1,
                fact_sha256=f"{index:064x}",
                coverage_from=LocalDate(date(2026, 1, 1)),
                coverage_through=AS_OF,
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
    assert tuple(
        str(entry_id)
        for entry_id in persistence.calls[0]["command"].economic_fact_entry_ids
    ) == (
        "50000000-0000-0000-0000-000000000005",
        "50000000-0000-0000-0000-000000000006",
    )
    canonical = persistence.calls[0]["evidence"]
    assert len(canonical) == 13
    assert [item.issuer for item in canonical if item.kind is ReconstructionEvidenceKind.LOANS] == [
        ReconstructionEvidenceIssuer.BANKING,
        ReconstructionEvidenceIssuer.CORPORATE_GOVERNANCE,
    ]


def test_source_owned_evidence_carries_a_positive_immutable_revision() -> None:
    item = complete_evidence()[0]

    revised = ReconstructionEvidence(
        kind=item.kind,
        confirmation=item.confirmation,
        issuer=item.issuer,
        source_record_id=item.source_record_id,
        source_revision=2,
        fact_sha256=item.fact_sha256,
        coverage_from=item.coverage_from,
        coverage_through=item.coverage_through,
    )

    assert revised.source_revision == 2


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
        source_revision=item.source_revision,
        fact_sha256=item.fact_sha256,
        coverage_from=item.coverage_from,
        coverage_through=item.coverage_through,
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


def test_duplicate_economic_fact_entry_fails_closed_without_persistence() -> None:
    persistence = ReconstructionPersistenceStub()
    duplicate_id = LedgerEntryId("50000000-0000-0000-0000-000000000005")
    invalid = replace(
        command(complete_evidence()),
        economic_fact_entry_ids=(duplicate_id, duplicate_id),
    )

    with pytest.raises(LedgerError) as failure:
        asyncio.run(LedgerService(persistence).record_reconstruction_assessment(invalid))

    assert failure.value.code == "LEDGER_RECONSTRUCTION_ECONOMIC_FACTS_INVALID"
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
        source_revision=item.source_revision,
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


def test_every_source_owner_must_attest_january_first_to_cutoff_coverage() -> None:
    persistence = ReconstructionPersistenceStub()
    evidence = list(complete_evidence())
    index = next(
        index
        for index, item in enumerate(evidence)
        if item.kind is ReconstructionEvidenceKind.INVESTMENTS
    )
    item = evidence[index]
    evidence[index] = ReconstructionEvidence(
        kind=item.kind,
        confirmation=item.confirmation,
        issuer=item.issuer,
        source_record_id=item.source_record_id,
        source_revision=item.source_revision,
        fact_sha256=item.fact_sha256,
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


def fact_reference(
    capability: LedgerSourceCapability,
    record_id: str,
    digest_character: str,
) -> LedgerFactReference:
    return LedgerFactReference(
        capability=capability,
        record_id=LedgerSourceRecordId(record_id),
        revision=1,
        fact_sha256=digest_character * 64,
    )


def opening_position_command() -> RebuildCompanyYearOpeningCommand:
    return RebuildCompanyYearOpeningCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("ledger-opening-position-test"),
        idempotency_key=IdempotencyKey("opening-position-2026"),
        income_year=INCOME_YEAR,
        opening_date=LocalDate(date(2026, 1, 1)),
        mode=OpeningPositionMode.PRIOR_CLOSE_RECONSTRUCTION,
        opening_basis=LedgerFactReference(
            capability=LedgerSourceCapability.ANNUAL_ACCOUNTS_FILING,
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
            OpeningBankLoanComponent(
                loan_reference_id=BankLoanReferenceId("bank-loan:prior-year:2"),
                maturity=BankLoanMaturity.LONG_TERM,
                amount=Money.nok("25000.00"),
                primary_source=fact_reference(
                    LedgerSourceCapability.BANKING, "fact:bank-loan:prior-year:2", "2"
                ),
                corroborating_sources=(
                    fact_reference(
                        LedgerSourceCapability.DOCUMENTS,
                        "document:bank-loan:prior-year:2",
                        "2",
                    ),
                ),
            ),
            opening_component(
                OpeningBalanceCategory.BANK,
                "bank-account:1",
                "105000.00",
                LedgerSourceCapability.BANKING,
                "3",
            ),
            OpeningBankLoanComponent(
                loan_reference_id=BankLoanReferenceId("bank-loan:prior-year:1"),
                maturity=BankLoanMaturity.LONG_TERM,
                amount=Money.nok("50000.00"),
                primary_source=fact_reference(
                    LedgerSourceCapability.BANKING, "fact:bank-loan:prior-year:1", "4"
                ),
                corroborating_sources=(
                    fact_reference(
                        LedgerSourceCapability.DOCUMENTS,
                        "document:bank-loan:prior-year:1",
                        "4",
                    ),
                ),
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
    canonical = call["components"]
    assert [component.category for component in canonical] == [
        OpeningBalanceCategory.BANK,
        OpeningBalanceCategory.LONG_TERM_BANK_LOAN_PAYABLE,
        OpeningBalanceCategory.LONG_TERM_BANK_LOAN_PAYABLE,
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
    with pytest.raises(LedgerError) as failure:
        OpeningBalanceComponent(
            category=OpeningBalanceCategory.BANK,
            reference_id=LedgerSourceRecordId("bank:duplicate-source"),
            amount=Money.nok("100.00"),
            primary_source=fact_reference(LedgerSourceCapability.BANKING, "same", "a"),
            corroborating_sources=(
                fact_reference(LedgerSourceCapability.BANKING, "same", "a"),
            ),
        )

    assert failure.value.code == "LEDGER_OPENING_SOURCE_OVERLAP"
    assert persistence.calls == []


def test_opening_contract_has_typed_lifecycle_components_and_no_count_cap() -> None:
    source = fact_reference(LedgerSourceCapability.BANKING, "bank", "a")
    document = fact_reference(LedgerSourceCapability.DOCUMENTS, "document", "b")

    loan = OpeningBankLoanComponent(
        loan_reference_id=BankLoanReferenceId("loan:2025:1"),
        maturity=BankLoanMaturity.SHORT_TERM,
        amount=Money.nok("100.00"),
        primary_source=source,
        corroborating_sources=(document,),
    )
    increase = OpeningCapitalIncreaseComponent(
        capital_increase_reference_id=CapitalIncreaseReferenceId("increase:2025:1"),
        phase=CapitalIncreasePhase.RESTRICTED_PAYMENT,
        nominal_increase=Money.nok("80.00"),
        share_premium=Money.nok("20.00"),
        primary_source=fact_reference(
            LedgerSourceCapability.CORPORATE_GOVERNANCE, "increase-decision", "c"
        ),
        corroborating_sources=(source, document),
    )
    reduction = OpeningCapitalReductionComponent(
        capital_reduction_reference_id=CapitalReductionReferenceId("reduction:2025:1"),
        recognition=CapitalReductionRecognition.DECIDED_NOT_REGISTERED,
        nominal_reduction=Money.nok("30.00"),
        primary_source=fact_reference(
            LedgerSourceCapability.CORPORATE_GOVERNANCE, "reduction-decision", "d"
        ),
        corroborating_sources=(document,),
    )
    dividend = OpeningDividendReceivableComponent(
        decision_reference_id=DividendDecisionReferenceId("dividend:2025:1"),
        amount=Money.nok("50.00"),
        primary_source=fact_reference(
            LedgerSourceCapability.INVESTMENTS, "dividend-decision", "e"
        ),
        corroborating_sources=(document,),
    )

    assert loan.category is OpeningBalanceCategory.SHORT_TERM_BANK_LOAN_PAYABLE
    assert increase.phase is CapitalIncreasePhase.RESTRICTED_PAYMENT
    assert reduction.recognition is CapitalReductionRecognition.DECIDED_NOT_REGISTERED
    assert dividend.category is OpeningBalanceCategory.DIVIDEND_RECEIVABLE

    components = tuple(
        OpeningBalanceComponent(
            category=OpeningBalanceCategory.BANK,
            reference_id=LedgerSourceRecordId(f"bank:{index}"),
            amount=Money.nok("1.00"),
            primary_source=fact_reference(
                LedgerSourceCapability.BANKING,
                f"bank-source:{index}",
                format(index % 16, "x"),
            ),
            corroborating_sources=(
                fact_reference(
                    LedgerSourceCapability.DOCUMENTS,
                    f"bank-document:{index}",
                    format((index + 1) % 16, "x"),
                ),
            ),
        )
        for index in range(64)
    )
    command = replace(
        opening_position_command(),
        mode=OpeningPositionMode.PRIOR_CLOSE_RECONSTRUCTION,
        components=components,
    )
    assert len(command.components) == 64


def test_opening_compiler_preserves_lifecycle_phase_and_complete_classification() -> None:
    persistence = ReconstructionPersistenceStub()
    annual_accounts = fact_reference(
        LedgerSourceCapability.ANNUAL_ACCOUNTS_FILING, "annual-accounts:2025", "f"
    )
    documents = fact_reference(LedgerSourceCapability.DOCUMENTS, "archive:2025", "1")
    governance = fact_reference(
        LedgerSourceCapability.CORPORATE_GOVERNANCE, "increase:decision", "2"
    )
    banking = fact_reference(LedgerSourceCapability.BANKING, "restricted-bank", "3")
    command = replace(
        opening_position_command(),
        mode=OpeningPositionMode.PRIOR_CLOSE_RECONSTRUCTION,
        opening_basis=annual_accounts,
        components=(
            OpeningCapitalIncreaseComponent(
                capital_increase_reference_id=CapitalIncreaseReferenceId("increase:1"),
                phase=CapitalIncreasePhase.RESTRICTED_PAYMENT,
                nominal_increase=Money.nok("80.00"),
                share_premium=Money.nok("20.00"),
                primary_source=governance,
                corroborating_sources=(banking, documents),
            ),
            OpeningInvestmentComponent(
                investment_reference_id=LedgerSourceRecordId("fund:1"),
                classification=InvestmentClassification.CURRENT_FUND,
                amount=Money.nok("25.00"),
                primary_source=fact_reference(
                    LedgerSourceCapability.INVESTMENTS, "fund-position", "4"
                ),
                corroborating_sources=(documents,),
            ),
            OpeningBalanceComponent(
                category=OpeningBalanceCategory.DEFERRED_TAX_ASSET,
                reference_id=LedgerSourceRecordId("deferred-tax:2025"),
                amount=Money.nok("75.00"),
                primary_source=fact_reference(
                    LedgerSourceCapability.COMPANY_TAX_FILING, "tax:2025", "5"
                ),
                corroborating_sources=(documents,),
            ),
            OpeningBalanceComponent(
                category=OpeningBalanceCategory.RETAINED_EARNINGS,
                reference_id=LedgerSourceRecordId("retained:2025"),
                amount=Money.nok("100.00"),
                primary_source=annual_accounts,
                corroborating_sources=(documents,),
            ),
        ),
    )

    asyncio.run(LedgerService(persistence).rebuild_company_year_opening(command))

    call = persistence.calls[0]
    lines = call["lines"]
    assert [(line.account, str(line.debit.amount), str(line.credit.amount)) for line in lines] == [
        ("1815", "25.00", "0.00"),
        ("1070", "75.00", "0.00"),
        ("1921", "100.00", "0.00"),
        ("2050", "0.00", "100.00"),
        ("2030", "0.00", "100.00"),
    ]
    compiled = call["components"]
    assert compiled[2].lifecycle_phase == "RESTRICTED_PAYMENT"
    assert compiled[2].reference_id == "increase:1"


def test_opening_golden_fixture_matches_the_python_compiler() -> None:
    fixture_path = (
        Path(__file__).parents[3] / "tests" / "fixtures" / "ledger-supported-patterns.json"
    )
    fixture = json.loads(fixture_path.read_text())
    golden = next(
        pattern for pattern in fixture["patterns"] if pattern["id"] == "opening-rebuild"
    )
    source_facts = golden["input"]["sources"]

    def source(source_key: str) -> LedgerFactReference:
        value = source_facts[source_key]
        return LedgerFactReference(
            capability=LedgerSourceCapability(value["capability"]),
            record_id=LedgerSourceRecordId(value["recordId"]),
            revision=value["revision"],
            fact_sha256=value["factSha256"],
        )

    def sources(
        value: dict[str, object],
    ) -> tuple[LedgerFactReference, tuple[LedgerFactReference, ...]]:
        return (
            source(str(value["primarySource"])),
            tuple(source(str(key)) for key in value["corroboratingSources"]),
        )

    def component(value: dict[str, object]) -> object:
        primary, corroborating = sources(value)
        common = {
            "primary_source": primary,
            "corroborating_sources": corroborating,
        }
        kind = value["componentKind"]
        if kind == "CLASSIFIED_BALANCE":
            return OpeningBalanceComponent(
                category=OpeningBalanceCategory(str(value["category"])),
                reference_id=LedgerSourceRecordId(str(value["referenceId"])),
                amount=Money.nok(str(value["amountNok"])),
                **common,
            )
        if kind == "BANK_LOAN":
            return OpeningBankLoanComponent(
                loan_reference_id=BankLoanReferenceId(
                    str(value["loanReferenceId"])
                ),
                maturity=BankLoanMaturity(str(value["maturity"])),
                amount=Money.nok(str(value["amountNok"])),
                **common,
            )
        if kind == "INVESTMENT":
            return OpeningInvestmentComponent(
                investment_reference_id=LedgerSourceRecordId(
                    str(value["investmentReferenceId"])
                ),
                classification=InvestmentClassification(str(value["classification"])),
                amount=Money.nok(str(value["amountNok"])),
                **common,
            )
        if kind == "CAPITAL_INCREASE":
            return OpeningCapitalIncreaseComponent(
                capital_increase_reference_id=CapitalIncreaseReferenceId(
                    str(value["capitalIncreaseReferenceId"])
                ),
                phase=CapitalIncreasePhase(str(value["phase"])),
                nominal_increase=Money.nok(str(value["nominalIncreaseNok"])),
                share_premium=Money.nok(str(value["sharePremiumNok"])),
                **common,
            )
        if kind == "CAPITAL_REDUCTION":
            return OpeningCapitalReductionComponent(
                capital_reduction_reference_id=CapitalReductionReferenceId(
                    str(value["capitalReductionReferenceId"])
                ),
                recognition=CapitalReductionRecognition(str(value["recognition"])),
                nominal_reduction=Money.nok(str(value["nominalReductionNok"])),
                **common,
            )
        dividend_common = {
            "decision_reference_id": DividendDecisionReferenceId(
                str(value["decisionReferenceId"])
            ),
            "amount": Money.nok(str(value["amountNok"])),
            **common,
        }
        if kind == "DIVIDEND_RECEIVABLE":
            return OpeningDividendReceivableComponent(**dividend_common)
        if kind == "DIVIDEND_PAYABLE":
            return OpeningDividendPayableComponent(**dividend_common)
        raise AssertionError(f"unsupported golden opening component {kind}")

    command = replace(
        opening_position_command(),
        mode=OpeningPositionMode(golden["input"]["mode"]),
        opening_basis=source(golden["input"]["openingBasis"]),
        components=tuple(component(value) for value in golden["input"]["components"]),
    )
    persistence = ReconstructionPersistenceStub()

    asyncio.run(LedgerService(persistence).rebuild_company_year_opening(command))

    call = persistence.calls[0]
    compiled = call["components"]
    lines = call["lines"]
    expected_lines = sorted(
        golden["journals"][0]["lines"],
        key=lambda line: (line["category"], line["referenceId"], line["componentKind"]),
    )
    assert [
        (
            item.component_kind,
            item.category.value,
            item.reference_id,
            item.lifecycle_phase,
            item.account,
            f"{item.amount.amount:.2f}",
            item.is_debit,
        )
        for item in compiled
    ] == [
        (
            line["componentKind"],
            line["category"],
            line["referenceId"],
            line["lifecyclePhase"],
            line["postingAccount"],
            line["debitNok"] if line["debitNok"] != "0.00" else line["creditNok"],
            line["debitNok"] != "0.00",
        )
        for line in expected_lines
    ]
    assert [
        (line.account, f"{line.debit.amount:.2f}", f"{line.credit.amount:.2f}")
        for line in lines
    ] == [
        (line["postingAccount"], line["debitNok"], line["creditNok"])
        for line in expected_lines
    ]
    assert len(call["entry_sources"]) == len(source_facts)
