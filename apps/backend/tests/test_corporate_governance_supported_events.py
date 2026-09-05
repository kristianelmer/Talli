from dataclasses import replace
from datetime import date

import pytest

from talli_backend.modules.corporate_governance.public import (
    BankLoanEventFacts,
    BankTransactionReference,
    CashCapitalIncreaseEventFacts,
    CorporateGovernanceError,
    CorporateGovernanceErrorCode,
    CorporateSourceReference,
    DocumentReference,
    GroupContributionEventFacts,
    IntercompanyLoanEventFacts,
    LossCoverageCapitalReductionEventFacts,
    OwnerLoanEventFacts,
    RecordSupportedCorporateEventCommand,
    SupportedCorporateBankFact,
    SupportedCorporateDocumentFact,
    SupportedCorporateEventId,
    SupportedCorporateEventKind,
    SupportedCorporateEventPhase,
    SupportedCorporateEventReference,
    SupportedCorporateEvidenceKind,
    SupportedCorporatePerspective,
    SupportedCorporateRelationship,
    SupportedCorporateSourceFact,
)
from talli_backend.modules.corporate_governance.service import (
    CorporateGovernanceService,
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
    UserId,
)

COMPANY_ID = CompanyId("10000000-0000-0000-0000-000000000001")
ACTOR_ID = ActorId(
    ActorKind.USER,
    UserId("11000000-0000-0000-0000-000000000001"),
)
EVENT_ID = SupportedCorporateEventId("20000000-0000-0000-0000-000000000001")
REFERENCE_ID = SupportedCorporateEventReference(
    "30000000-0000-0000-0000-000000000001"
)
HASH_A = "a" * 64
HASH_B = "b" * 64


def document(
    kind: SupportedCorporateEvidenceKind,
    suffix: int,
) -> SupportedCorporateDocumentFact:
    return SupportedCorporateDocumentFact(
        document_id=DocumentReference(
            f"40000000-0000-0000-0000-{suffix:012d}"
        ),
        evidence_kind=kind,
        revision=1,
        content_sha256=HASH_A,
    )


def source(suffix: int = 1) -> SupportedCorporateSourceFact:
    return SupportedCorporateSourceFact(
        record_id=CorporateSourceReference(
            f"50000000-0000-0000-0000-{suffix:012d}"
        ),
        revision=1,
        fact_sha256=HASH_B,
    )


def bank(amount: str) -> SupportedCorporateBankFact:
    return SupportedCorporateBankFact(
        transaction_id=BankTransactionReference(
            "60000000-0000-0000-0000-000000000001"
        ),
        transaction_date=LocalDate(date(2026, 9, 1)),
        signed_amount=Money.nok(amount),
        source_sha256=HASH_B,
    )


def test_owner_to_company_loan_is_supported_only_with_complete_ordinary_evidence() -> None:
    prepared = CorporateGovernanceService().prepare_supported_event(
        command(
            kind=SupportedCorporateEventKind.OWNER_LOAN,
            phase=SupportedCorporateEventPhase.FUNDING,
            facts=OwnerLoanEventFacts(
                principal=Money.nok("125000"),
                owner_name="Kari Nordmann",
                owner_is_recorded_shareholder=True,
                norwegian_owner=True,
                signed_agreement=True,
                ordinary_terms=True,
                approval_or_exemption_evidenced=True,
                interest_and_tax_treatment_cleared=True,
                no_security_or_conversion=True,
                no_complex_terms=True,
            ),
            documents=(document(SupportedCorporateEvidenceKind.SIGNED_AGREEMENT, 1),),
            bank_fact=bank("125000"),
        )
    )

    assert prepared.event_kind is SupportedCorporateEventKind.OWNER_LOAN
    assert prepared.canonical_facts["businessFacts"]["principal"]["amount"] == "125000.00"


def test_owner_loan_blocks_outbound_or_unproved_funding() -> None:
    with pytest.raises(CorporateGovernanceError) as caught:
        CorporateGovernanceService().prepare_supported_event(
            command(
                kind=SupportedCorporateEventKind.OWNER_LOAN,
                phase=SupportedCorporateEventPhase.FUNDING,
                facts=OwnerLoanEventFacts(
                    principal=Money.nok("125000"),
                    owner_name="Kari Nordmann",
                    owner_is_recorded_shareholder=True,
                    norwegian_owner=True,
                    signed_agreement=True,
                    ordinary_terms=True,
                    approval_or_exemption_evidenced=False,
                    interest_and_tax_treatment_cleared=True,
                    no_security_or_conversion=True,
                    no_complex_terms=True,
                ),
                documents=(document(SupportedCorporateEvidenceKind.SIGNED_AGREEMENT, 1),),
                bank_fact=bank("-125000"),
            )
        )

    assert caught.value.code == CorporateGovernanceErrorCode.CORPORATE_EVENT_JUDGMENT_REQUIRED.value


def command(
    *,
    kind: SupportedCorporateEventKind,
    phase: SupportedCorporateEventPhase,
    facts: object,
    documents: tuple[SupportedCorporateDocumentFact, ...],
    bank_fact: SupportedCorporateBankFact | None = None,
    shareholder_register_fact: SupportedCorporateSourceFact | None = None,
    tax_calculation_fact: SupportedCorporateSourceFact | None = None,
) -> RecordSupportedCorporateEventCommand:
    return RecordSupportedCorporateEventCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("issue-191-golden"),
        idempotency_key=IdempotencyKey("issue-191-golden-idempotency"),
        income_year=IncomeYear(2026),
        event_id=EVENT_ID,
        event_reference=REFERENCE_ID,
        event_date=LocalDate(date(2026, 9, 1)),
        event_kind=kind,
        phase=phase,
        facts=facts,  # type: ignore[arg-type]
        document_facts=documents,
        bank_fact=bank_fact,
        shareholder_register_fact=shareholder_register_fact,
        tax_calculation_fact=tax_calculation_fact,
    )


def capital_facts() -> CashCapitalIncreaseEventFacts:
    return CashCapitalIncreaseEventFacts(
        nominal_increase=Money.nok("10000.00"),
        share_premium=Money.nok("5000.00"),
        issued_share_count=100,
        single_ordinary_class=True,
        cash_only=True,
        binding_subscription=True,
        full_timely_payment=True,
        independent_confirmation=True,
        register_reconciled=True,
        norwegian_subscribers_only=True,
        no_special_terms=True,
        no_direct_use_exception=True,
        issue_costs_resolved=True,
    )


@pytest.mark.parametrize(
    ("phase", "documents", "bank_fact", "register_fact"),
    [
        (
            SupportedCorporateEventPhase.BINDING_SUBSCRIPTION,
            (document(SupportedCorporateEvidenceKind.SIGNED_DECISION, 1),),
            None,
            None,
        ),
        (
            SupportedCorporateEventPhase.RESTRICTED_PAYMENT,
            (
                document(SupportedCorporateEvidenceKind.SIGNED_DECISION, 1),
                document(
                    SupportedCorporateEvidenceKind.CONTRIBUTION_CONFIRMATION, 2
                ),
            ),
            bank("15000.00"),
            None,
        ),
        (
            SupportedCorporateEventPhase.REGISTERED,
            (
                document(SupportedCorporateEvidenceKind.SIGNED_DECISION, 1),
                document(
                    SupportedCorporateEvidenceKind.CONTRIBUTION_CONFIRMATION, 2
                ),
                document(SupportedCorporateEvidenceKind.AMENDED_ARTICLES, 3),
                document(SupportedCorporateEvidenceKind.REGISTRATION_RECEIPT, 4),
            ),
            bank("15000.00"),
            source(),
        ),
    ],
)
def test_cash_capital_increase_phases_are_canonical_and_versioned(
    phase: SupportedCorporateEventPhase,
    documents: tuple[SupportedCorporateDocumentFact, ...],
    bank_fact: SupportedCorporateBankFact | None,
    register_fact: SupportedCorporateSourceFact | None,
) -> None:
    result = CorporateGovernanceService().prepare_supported_event(
        command(
            kind=SupportedCorporateEventKind.CASH_CAPITAL_INCREASE,
            phase=phase,
            facts=capital_facts(),
            documents=documents,
            bank_fact=bank_fact,
            shareholder_register_fact=register_fact,
        )
    )

    assert result.policy_version == "corporate-governance-supported-events-2026.1"
    assert len(result.facts_sha256) == 64
    assert result.canonical_facts["phase"] == phase.value


def test_non_cash_capital_is_blocked_before_a_canonical_event_exists() -> None:
    request = command(
        kind=SupportedCorporateEventKind.CASH_CAPITAL_INCREASE,
        phase=SupportedCorporateEventPhase.BINDING_SUBSCRIPTION,
        facts=replace(capital_facts(), cash_only=False),
        documents=(document(SupportedCorporateEvidenceKind.SIGNED_DECISION, 1),),
    )

    with pytest.raises(CorporateGovernanceError) as failure:
        CorporateGovernanceService().prepare_supported_event(request)

    assert failure.value.code is CorporateGovernanceErrorCode.UNSUPPORTED_CORPORATE_EVENT


def reduction_facts() -> LossCoverageCapitalReductionEventFacts:
    return LossCoverageCapitalReductionEventFacts(
        nominal_reduction=Money.nok("20000.00"),
        old_share_capital=Money.nok("50000.00"),
        new_share_capital=Money.nok("30000.00"),
        single_ordinary_class=True,
        unchanged_owners_and_share_count=True,
        loss_only=True,
        loss_evidenced=True,
        other_equity_exhausted=True,
        no_value_transfer=True,
        no_creditor_notice=True,
        no_simultaneous_capital_change=True,
        register_reconciled=True,
    )


def test_registered_loss_coverage_reduction_requires_no_cash_and_register_evidence() -> None:
    result = CorporateGovernanceService().prepare_supported_event(
        command(
            kind=SupportedCorporateEventKind.LOSS_COVERAGE_CAPITAL_REDUCTION,
            phase=SupportedCorporateEventPhase.REGISTERED,
            facts=reduction_facts(),
            documents=(
                document(SupportedCorporateEvidenceKind.SIGNED_DECISION, 1),
                document(SupportedCorporateEvidenceKind.AMENDED_ARTICLES, 2),
                document(SupportedCorporateEvidenceKind.REGISTRATION_RECEIPT, 3),
            ),
            shareholder_register_fact=source(),
        )
    )

    assert result.event_kind is SupportedCorporateEventKind.LOSS_COVERAGE_CAPITAL_REDUCTION


@pytest.mark.parametrize(
    "unsafe",
    [
        {"no_value_transfer": False},
        {"unchanged_owners_and_share_count": False},
        {"no_simultaneous_capital_change": False},
    ],
)
def test_repayment_reorganization_and_combined_reduction_routes_block(
    unsafe: dict[str, bool],
) -> None:
    with pytest.raises(CorporateGovernanceError) as failure:
        CorporateGovernanceService().prepare_supported_event(
            command(
                kind=SupportedCorporateEventKind.LOSS_COVERAGE_CAPITAL_REDUCTION,
                phase=SupportedCorporateEventPhase.DECIDED_NOT_REGISTERED,
                facts=replace(reduction_facts(), **unsafe),
                documents=(
                    document(SupportedCorporateEvidenceKind.SIGNED_DECISION, 1),
                    document(SupportedCorporateEvidenceKind.AMENDED_ARTICLES, 2),
                ),
            )
        )

    assert failure.value.code is CorporateGovernanceErrorCode.UNSUPPORTED_CORPORATE_EVENT


def test_ordinary_nok_bank_loan_payment_freezes_lender_allocation() -> None:
    result = CorporateGovernanceService().prepare_supported_event(
        command(
            kind=SupportedCorporateEventKind.BANK_LOAN,
            phase=SupportedCorporateEventPhase.PAYMENT,
            facts=BankLoanEventFacts(
                principal=Money.nok("9000.00"),
                interest=Money.nok("900.00"),
                fee=Money.nok("100.00"),
                lender_name="Norsk Bank ASA",
                norwegian_lender=True,
                signed_agreement=True,
                lender_allocation_confirmed=True,
                ordinary_terms=True,
                no_complex_terms=True,
            ),
            documents=(
                document(SupportedCorporateEvidenceKind.LENDER_STATEMENT, 1),
            ),
            bank_fact=bank("-10000.00"),
        )
    )

    assert result.canonical_facts["eventKind"] == "bank_loan"


def test_intercompany_funding_requires_norwegian_ordinary_arm_length_facts() -> None:
    facts = IntercompanyLoanEventFacts(
        perspective=SupportedCorporatePerspective.BORROWER,
        relationship=SupportedCorporateRelationship.PARENT_TO_SUBSIDIARY,
        principal=Money.nok("80000.00"),
        counterparty_name="Morselskap AS",
        counterparty_organization_number="987654321",
        norwegian_counterparty=True,
        signed_agreement=True,
        ordinary_terms=True,
        approval_or_exemption_evidenced=True,
        arm_length_confirmed=True,
        interest_limitation_cleared=True,
        no_complex_terms=True,
    )
    result = CorporateGovernanceService().prepare_supported_event(
        command(
            kind=SupportedCorporateEventKind.INTERCOMPANY_LOAN,
            phase=SupportedCorporateEventPhase.FUNDING,
            facts=facts,
            documents=(document(SupportedCorporateEvidenceKind.SIGNED_AGREEMENT, 1),),
            bank_fact=bank("80000.00"),
        )
    )
    assert result.event_kind is SupportedCorporateEventKind.INTERCOMPANY_LOAN

    with pytest.raises(CorporateGovernanceError) as failure:
        CorporateGovernanceService().prepare_supported_event(
            replace(
                command(
                    kind=SupportedCorporateEventKind.INTERCOMPANY_LOAN,
                    phase=SupportedCorporateEventPhase.FUNDING,
                    facts=replace(facts, norwegian_counterparty=False),
                    documents=(
                        document(SupportedCorporateEvidenceKind.SIGNED_AGREEMENT, 1),
                    ),
                    bank_fact=bank("80000.00"),
                )
            )
        )
    assert failure.value.code is CorporateGovernanceErrorCode.CORPORATE_EVENT_JUDGMENT_REQUIRED


@pytest.mark.parametrize(
    ("relationship", "perspective", "post_acquisition", "impairment"),
    [
        (
            SupportedCorporateRelationship.SUBSIDIARY_TO_PARENT,
            SupportedCorporatePerspective.RECIPIENT,
            True,
            False,
        ),
        (
            SupportedCorporateRelationship.PARENT_TO_SUBSIDIARY,
            SupportedCorporatePerspective.GIVER,
            False,
            True,
        ),
        (
            SupportedCorporateRelationship.SISTER_TO_SISTER,
            SupportedCorporatePerspective.RECIPIENT,
            False,
            False,
        ),
    ],
)
def test_group_contribution_accepts_only_the_three_frozen_cost_method_routes(
    relationship: SupportedCorporateRelationship,
    perspective: SupportedCorporatePerspective,
    post_acquisition: bool,
    impairment: bool,
) -> None:
    result = CorporateGovernanceService().prepare_supported_event(
        command(
            kind=SupportedCorporateEventKind.GROUP_CONTRIBUTION,
            phase=SupportedCorporateEventPhase.DECISION,
            facts=GroupContributionEventFacts(
                relationship=relationship,
                perspective=perspective,
                gross_tax_amount=Money.nok("10000.00"),
                related_tax=Money.nok("2200.00"),
                after_tax_accounting_amount=Money.nok("7800.00"),
                counterparty_name="Konsernselskap AS",
                counterparty_organization_number="987654321",
                both_norwegian=True,
                ownership_basis_points=10000,
                voting_basis_points=10000,
                year_end_group_eligibility_proved=True,
                corporate_approval_evidenced=True,
                distribution_capacity_confirmed=True,
                prudent_equity_and_liquidity_confirmed=True,
                post_acquisition_income_proved=post_acquisition,
                impairment_cleared=impairment,
                no_equity_method=True,
                no_non_cash_or_circular_route=True,
                consolidation_not_required=True,
            ),
            documents=(document(SupportedCorporateEvidenceKind.SIGNED_DECISION, 1),),
            tax_calculation_fact=source(),
        )
    )

    assert result.event_kind is SupportedCorporateEventKind.GROUP_CONTRIBUTION


def test_group_contribution_threshold_and_consolidation_uncertainty_block() -> None:
    base = GroupContributionEventFacts(
        relationship=SupportedCorporateRelationship.SUBSIDIARY_TO_PARENT,
        perspective=SupportedCorporatePerspective.RECIPIENT,
        gross_tax_amount=Money.nok("10000.00"),
        related_tax=Money.nok("2200.00"),
        after_tax_accounting_amount=Money.nok("7800.00"),
        counterparty_name="Konsernselskap AS",
        counterparty_organization_number="987654321",
        both_norwegian=True,
        ownership_basis_points=9000,
        voting_basis_points=10000,
        year_end_group_eligibility_proved=True,
        corporate_approval_evidenced=True,
        distribution_capacity_confirmed=True,
        prudent_equity_and_liquidity_confirmed=True,
        post_acquisition_income_proved=True,
        impairment_cleared=False,
        no_equity_method=True,
        no_non_cash_or_circular_route=True,
        consolidation_not_required=False,
    )
    with pytest.raises(CorporateGovernanceError) as failure:
        CorporateGovernanceService().prepare_supported_event(
            command(
                kind=SupportedCorporateEventKind.GROUP_CONTRIBUTION,
                phase=SupportedCorporateEventPhase.DECISION,
                facts=base,
                documents=(document(SupportedCorporateEvidenceKind.SIGNED_DECISION, 1),),
                tax_calculation_fact=source(),
            )
        )

    assert failure.value.code is CorporateGovernanceErrorCode.UNSUPPORTED_CORPORATE_EVENT


def test_kind_fact_mismatch_is_rejected() -> None:
    with pytest.raises(CorporateGovernanceError) as failure:
        CorporateGovernanceService().prepare_supported_event(
            command(
                kind=SupportedCorporateEventKind.BANK_LOAN,
                phase=SupportedCorporateEventPhase.BINDING_SUBSCRIPTION,
                facts=capital_facts(),
                documents=(document(SupportedCorporateEvidenceKind.SIGNED_DECISION, 1),),
            )
        )

    assert failure.value.code is CorporateGovernanceErrorCode.UNSUPPORTED_CORPORATE_EVENT
