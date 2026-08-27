from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import cast

import pytest

from talli_backend.modules.ledger.public import (
    ApprovedLossCoverageCapitalReductionFacts,
    ApprovedOneSidedIntercompanyLoanFundingFacts,
    ApprovedOwnerLoanFundingFacts,
    BankInterestIncomeFacts,
    BankLoanEvent,
    CashCapitalIncreaseFacts,
    CapitalIncreasePhase,
    CapitalReductionRecognition,
    CompanyTaxAccrualFacts,
    GroupContributionFacts,
    GroupContributionPerspective,
    GroupContributionRelationship,
    IntercompanyLoanPerspective,
    IntercompanyLoanRelationship,
    InvestmentDividendFacts,
    InvestmentDividendPhase,
    LedgerEntryId,
    LedgerEntryKind,
    LedgerError,
    LedgerFactReference,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    OrdinaryBankLoanFacts,
    PostedLedgerEntry,
    RecognizeHoldingActionCommand,
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


class PatternPersistenceStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def post_entry(self, command: object, **draft: object) -> PostedLedgerEntry:
        self.calls.append({"command": command, **draft})
        return PostedLedgerEntry(
            entry_id=LedgerEntryId("40000000-0000-0000-0000-000000000004"),
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            entry_kind=draft["entry_kind"],
            posted_at=Timestamp(datetime(2026, 8, 27, 10, tzinfo=UTC)),
            replayed=False,
        )

    async def record_received_dividend_decision(
        self, command: object, **draft: object
    ) -> PostedLedgerEntry:
        self.calls.append({"operation": "dividend_decision", "command": command, **draft})
        return PostedLedgerEntry(
            entry_id=LedgerEntryId("40000000-0000-0000-0000-000000000005"),
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.DIVIDEND_RECEIVED,
            posted_at=Timestamp(datetime(2026, 8, 27, 10, tzinfo=UTC)),
            replayed=False,
        )

    async def record_received_dividend_payment(
        self,
        command: object,
        *,
        decision_entry_id: LedgerEntryId,
        **draft: object,
    ) -> PostedLedgerEntry:
        self.calls.append(
            {
                "operation": "dividend_payment",
                "command": command,
                "decision_entry_id": decision_entry_id,
                **draft,
            }
        )
        return PostedLedgerEntry(
            entry_id=LedgerEntryId("40000000-0000-0000-0000-000000000006"),
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.DIVIDEND_RECEIVED,
            posted_at=Timestamp(datetime(2026, 8, 27, 10, tzinfo=UTC)),
            replayed=False,
        )


def source(
    capability: LedgerSourceCapability,
    suffix: str,
) -> LedgerFactReference:
    return LedgerFactReference(
        capability=capability,
        record_id=LedgerSourceRecordId(f"golden:{suffix}"),
        revision=1,
        fact_sha256=(suffix.encode().hex() + "0" * 64)[:64],
    )


def command(
    facts: object,
    primary: LedgerFactReference,
    *corroborating: LedgerFactReference,
) -> RecognizeHoldingActionCommand:
    return RecognizeHoldingActionCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("supported-pattern-test"),
        idempotency_key=IdempotencyKey("supported-pattern-golden-0001"),
        income_year=IncomeYear(2026),
        event_date=LocalDate(date(2026, 8, 27)),
        primary_source=primary,
        corroborating_sources=tuple(corroborating),
        facts=facts,
    )


def capital_reduction_facts(
    *,
    recognition: CapitalReductionRecognition = (
        CapitalReductionRecognition.DECIDED_NOT_REGISTERED
    ),
    nominal_reduction: Money = Money.nok("20000.00"),
) -> ApprovedLossCoverageCapitalReductionFacts:
    return ApprovedLossCoverageCapitalReductionFacts(
        recognition=recognition,
        nominal_reduction=nominal_reduction,
    )


def posted_lines(persistence: PatternPersistenceStub) -> list[tuple[str, str, str]]:
    return [
        (line.account, format(line.debit.amount, "f"), format(line.credit.amount, "f"))
        for line in persistence.calls[0]["lines"]
    ]


def test_bank_interest_is_selected_from_banking_facts_and_balanced() -> None:
    persistence = PatternPersistenceStub()

    result = asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                BankInterestIncomeFacts(amount=Money.nok("500.00")),
                source(LedgerSourceCapability.BANKING, "bank-interest"),
            )
        )
    )

    assert result.entry_kind is LedgerEntryKind.BANK_INTEREST
    assert posted_lines(persistence) == [
        ("1920", "500.00", "0.00"),
        ("8050", "0.00", "500.00"),
    ]


def test_investment_dividend_final_decision_recognizes_receivable_before_cash() -> None:
    persistence = PatternPersistenceStub()

    result = asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                InvestmentDividendFacts(
                    phase=InvestmentDividendPhase.FINAL_DECISION,
                    gross_amount=Money.nok("5000.00"),
                    decision_entry_id=None,
                ),
                source(LedgerSourceCapability.INVESTMENTS, "dividend-decision"),
                source(LedgerSourceCapability.DOCUMENTS, "dividend-decision-document"),
                source(
                    LedgerSourceCapability.COMPANY_TAX_FILING,
                    "dividend-decision-tax",
                ),
            )
        )
    )

    assert result.entry_id == LedgerEntryId("40000000-0000-0000-0000-000000000005")
    assert result.entry_kind is LedgerEntryKind.DIVIDEND_RECEIVED
    assert persistence.calls[0]["operation"] == "dividend_decision"
    assert posted_lines(persistence) == [
        ("1530", "5000.00", "0.00"),
        ("8070", "0.00", "5000.00"),
    ]


def test_investment_dividend_payment_clears_the_linked_decision_receivable() -> None:
    persistence = PatternPersistenceStub()
    decision_entry_id = LedgerEntryId("40000000-0000-0000-0000-000000000005")

    result = asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                InvestmentDividendFacts(
                    phase=InvestmentDividendPhase.PAYMENT,
                    gross_amount=Money.nok("5000.00"),
                    decision_entry_id=decision_entry_id,
                ),
                source(LedgerSourceCapability.INVESTMENTS, "dividend-payment"),
                source(LedgerSourceCapability.BANKING, "dividend-payment-bank"),
            )
        )
    )

    assert result.entry_id == LedgerEntryId("40000000-0000-0000-0000-000000000006")
    assert result.entry_kind is LedgerEntryKind.DIVIDEND_RECEIVED
    assert persistence.calls[0]["operation"] == "dividend_payment"
    assert persistence.calls[0]["decision_entry_id"] == decision_entry_id
    assert posted_lines(persistence) == [
        ("1920", "5000.00", "0.00"),
        ("1530", "0.00", "5000.00"),
    ]


@pytest.mark.parametrize(
    ("facts", "primary", "corroborating"),
    [
        (
            InvestmentDividendFacts(
                phase=InvestmentDividendPhase.FINAL_DECISION,
                gross_amount=Money.nok("5000.00"),
                decision_entry_id=None,
            ),
            source(LedgerSourceCapability.INVESTMENTS, "decision-missing-tax"),
            (source(LedgerSourceCapability.DOCUMENTS, "decision-document"),),
        ),
        (
            InvestmentDividendFacts(
                phase=InvestmentDividendPhase.FINAL_DECISION,
                gross_amount=Money.nok("5000.00"),
                decision_entry_id=None,
            ),
            source(LedgerSourceCapability.DOCUMENTS, "decision-wrong-primary"),
            (
                source(LedgerSourceCapability.INVESTMENTS, "decision-investments"),
                source(LedgerSourceCapability.COMPANY_TAX_FILING, "decision-tax"),
            ),
        ),
        (
            InvestmentDividendFacts(
                phase=InvestmentDividendPhase.PAYMENT,
                gross_amount=Money.nok("5000.00"),
                decision_entry_id=LedgerEntryId(
                    "40000000-0000-0000-0000-000000000005"
                ),
            ),
            source(LedgerSourceCapability.INVESTMENTS, "payment-missing-bank"),
            (),
        ),
        (
            InvestmentDividendFacts(
                phase=InvestmentDividendPhase.PAYMENT,
                gross_amount=Money.nok("5000.00"),
                decision_entry_id=LedgerEntryId(
                    "40000000-0000-0000-0000-000000000005"
                ),
            ),
            source(LedgerSourceCapability.INVESTMENTS, "payment-extra-document"),
            (
                source(LedgerSourceCapability.BANKING, "payment-bank"),
                source(LedgerSourceCapability.DOCUMENTS, "payment-document"),
            ),
        ),
    ],
)
def test_investment_dividend_requires_the_exact_phase_source_topology(
    facts: InvestmentDividendFacts,
    primary: LedgerFactReference,
    corroborating: tuple[LedgerFactReference, ...],
) -> None:
    persistence = PatternPersistenceStub()

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).recognize_holding_action(
                command(facts, primary, *corroborating)
            )
        )

    assert failure.value.code == "LEDGER_SOURCE_CAPABILITY_MISMATCH"
    assert persistence.calls == []


@pytest.mark.parametrize(
    "facts",
    [
        InvestmentDividendFacts(
            phase=InvestmentDividendPhase.FINAL_DECISION,
            gross_amount=Money.nok("5000.00"),
            decision_entry_id=LedgerEntryId("40000000-0000-0000-0000-000000000005"),
        ),
        InvestmentDividendFacts(
            phase=InvestmentDividendPhase.PAYMENT,
            gross_amount=Money.nok("5000.00"),
            decision_entry_id=None,
        ),
    ],
)
def test_investment_dividend_phase_requires_valid_decision_linkage(
    facts: InvestmentDividendFacts,
) -> None:
    persistence = PatternPersistenceStub()
    corroborating = (
        (
            source(LedgerSourceCapability.DOCUMENTS, "linkage-document"),
            source(LedgerSourceCapability.COMPANY_TAX_FILING, "linkage-tax"),
        )
        if facts.phase is InvestmentDividendPhase.FINAL_DECISION
        else (source(LedgerSourceCapability.BANKING, "linkage-bank"),)
    )

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).recognize_holding_action(
                command(
                    facts,
                    source(LedgerSourceCapability.INVESTMENTS, "invalid-linkage"),
                    *corroborating,
                )
            )
        )

    assert failure.value.code == "LEDGER_INVALID_INPUT"
    assert persistence.calls == []


def test_investment_dividend_rejects_runtime_invalid_phase_without_persistence(
) -> None:
    persistence = PatternPersistenceStub()

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).recognize_holding_action(
                command(
                    InvestmentDividendFacts(
                        phase=cast(InvestmentDividendPhase, "UNSUPPORTED"),
                        gross_amount=Money.nok("5000.00"),
                        decision_entry_id=LedgerEntryId(
                            "40000000-0000-0000-0000-000000000005"
                        ),
                    ),
                    source(
                        LedgerSourceCapability.INVESTMENTS,
                        "invalid-dividend-phase",
                    ),
                    source(
                        LedgerSourceCapability.BANKING,
                        "invalid-dividend-phase-bank",
                    ),
                )
            )
        )

    assert failure.value.code == "LEDGER_INVALID_INPUT"
    assert persistence.calls == []


@pytest.mark.parametrize(
    "phase",
    [InvestmentDividendPhase.FINAL_DECISION, InvestmentDividendPhase.PAYMENT],
)
def test_investment_dividend_requires_a_positive_amount(
    phase: InvestmentDividendPhase,
) -> None:
    persistence = PatternPersistenceStub()
    facts = InvestmentDividendFacts(
        phase=phase,
        gross_amount=Money.nok("0.00"),
        decision_entry_id=(
            None
            if phase is InvestmentDividendPhase.FINAL_DECISION
            else LedgerEntryId("40000000-0000-0000-0000-000000000005")
        ),
    )
    corroborating = (
        (
            source(LedgerSourceCapability.DOCUMENTS, "amount-document"),
            source(LedgerSourceCapability.COMPANY_TAX_FILING, "amount-tax"),
        )
        if phase is InvestmentDividendPhase.FINAL_DECISION
        else (source(LedgerSourceCapability.BANKING, "amount-bank"),)
    )

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).recognize_holding_action(
                command(
                    facts,
                    source(LedgerSourceCapability.INVESTMENTS, "zero-dividend"),
                    *corroborating,
                )
            )
        )

    assert failure.value.code == "LEDGER_INVALID_INPUT"
    assert persistence.calls == []


def test_tax_accrual_keeps_current_and_deferred_tax_distinct() -> None:
    persistence = PatternPersistenceStub()

    asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                CompanyTaxAccrualFacts(
                    current_tax=Money.nok("2200.00"),
                    deferred_tax_increase=Money.nok("300.00"),
                ),
                source(LedgerSourceCapability.COMPANY_TAX_FILING, "company-tax"),
            )
        )
    )

    assert posted_lines(persistence) == [
        ("8300", "2200.00", "0.00"),
        ("2500", "0.00", "2200.00"),
        ("8320", "300.00", "0.00"),
        ("2120", "0.00", "300.00"),
    ]


def test_bank_loan_payment_separates_principal_interest_and_fee() -> None:
    persistence = PatternPersistenceStub()

    asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                OrdinaryBankLoanFacts(
                    event=BankLoanEvent.PAYMENT,
                    principal=Money.nok("10000.00"),
                    interest=Money.nok("2000.00"),
                    fee=Money.nok("100.00"),
                ),
                source(LedgerSourceCapability.BANKING, "bank-loan-payment"),
            )
        )
    )

    assert posted_lines(persistence) == [
        ("2220", "10000.00", "0.00"),
        ("8150", "2000.00", "0.00"),
        ("7770", "100.00", "0.00"),
        ("1920", "0.00", "12100.00"),
    ]


def test_approved_owner_loan_funding_posts_bank_against_owner_debt() -> None:
    persistence = PatternPersistenceStub()

    asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                ApprovedOwnerLoanFundingFacts(principal=Money.nok("50000.00")),
                source(
                    LedgerSourceCapability.CORPORATE_GOVERNANCE,
                    "owner-loan-approval",
                ),
                source(LedgerSourceCapability.BANKING, "owner-loan-bank-match"),
            )
        )
    )

    assert posted_lines(persistence) == [
        ("1920", "50000.00", "0.00"),
        ("2255", "0.00", "50000.00"),
    ]


def test_bank_match_cannot_masquerade_as_the_owner_loan_approval() -> None:
    persistence = PatternPersistenceStub()

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).recognize_holding_action(
                command(
                    ApprovedOwnerLoanFundingFacts(principal=Money.nok("50000.00")),
                    source(LedgerSourceCapability.BANKING, "owner-loan-bank-primary"),
                    source(
                        LedgerSourceCapability.CORPORATE_GOVERNANCE,
                        "owner-loan-governance-corroborating",
                    ),
                )
            )
        )

    assert failure.value.code == "LEDGER_SOURCE_CAPABILITY_MISMATCH"
    assert persistence.calls == []


@pytest.mark.parametrize(
    ("perspective", "expected"),
    [
        (
            IntercompanyLoanPerspective.LENDER,
            [("1320", "80000.00", "0.00"), ("1920", "0.00", "80000.00")],
        ),
        (
            IntercompanyLoanPerspective.BORROWER,
            [("1920", "80000.00", "0.00"), ("2260", "0.00", "80000.00")],
        ),
    ],
)
def test_approved_intercompany_funding_posts_each_company_perspective(
    perspective: IntercompanyLoanPerspective,
    expected: list[tuple[str, str, str]],
) -> None:
    persistence = PatternPersistenceStub()

    asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                ApprovedOneSidedIntercompanyLoanFundingFacts(
                    perspective=perspective,
                    relationship=IntercompanyLoanRelationship.PARENT_TO_SUBSIDIARY,
                    principal=Money.nok("80000.00"),
                ),
                source(
                    LedgerSourceCapability.CORPORATE_GOVERNANCE,
                    "intercompany-shared-event",
                ),
                source(
                    LedgerSourceCapability.BANKING,
                    f"intercompany-bank-{perspective.value.lower()}",
                ),
            )
        )
    )

    assert posted_lines(persistence) == expected


def test_registered_cash_capital_reclassifies_nominal_premium_and_bank() -> None:
    persistence = PatternPersistenceStub()

    asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                CashCapitalIncreaseFacts(
                    phase=CapitalIncreasePhase.REGISTERED,
                    nominal_increase=Money.nok("10000.00"),
                    share_premium=Money.nok("5000.00"),
                ),
                source(LedgerSourceCapability.CORPORATE_GOVERNANCE, "capital-registration"),
            )
        )
    )

    assert posted_lines(persistence) == [
        ("2030", "15000.00", "0.00"),
        ("2000", "0.00", "10000.00"),
        ("2020", "0.00", "5000.00"),
        ("1920", "15000.00", "0.00"),
        ("1921", "0.00", "15000.00"),
    ]


def test_decided_loss_coverage_reduction_reclassifies_equity_without_cash() -> None:
    persistence = PatternPersistenceStub()

    asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                capital_reduction_facts(),
                source(
                    LedgerSourceCapability.CORPORATE_GOVERNANCE,
                    "capital-reduction-decision",
                ),
            )
        )
    )

    assert posted_lines(persistence) == [
        ("2033", "20000.00", "0.00"),
        ("2080", "0.00", "20000.00"),
    ]


def test_approved_loss_coverage_fact_requires_a_positive_accounting_amount() -> None:
    persistence = PatternPersistenceStub()

    with pytest.raises(LedgerError):
        asyncio.run(
            LedgerService(persistence).recognize_holding_action(
                command(
                    capital_reduction_facts(
                        nominal_reduction=Money.nok("0.00")
                    ),
                    source(
                        LedgerSourceCapability.CORPORATE_GOVERNANCE,
                        "capital-reduction-invalid-shape",
                    ),
                )
            )
        )

    assert persistence.calls == []


def test_first_seen_registered_reduction_posts_directly_against_loss() -> None:
    persistence = PatternPersistenceStub()

    asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                capital_reduction_facts(
                    recognition=(
                        CapitalReductionRecognition.FIRST_RECOGNIZED_AFTER_REGISTRATION
                    )
                ),
                source(
                    LedgerSourceCapability.CORPORATE_GOVERNANCE,
                    "capital-reduction-first-seen-registered",
                ),
            )
        )
    )

    assert posted_lines(persistence) == [
        ("2000", "20000.00", "0.00"),
        ("2080", "0.00", "20000.00"),
    ]


@pytest.mark.parametrize(
    ("relationship", "perspective", "expected"),
    [
        (
            GroupContributionRelationship.SUBSIDIARY_TO_PARENT,
            GroupContributionPerspective.RECIPIENT,
            [("1560", "7800.00", "0.00"), ("8075", "0.00", "7800.00")],
        ),
        (
            GroupContributionRelationship.PARENT_TO_SUBSIDIARY,
            GroupContributionPerspective.GIVER,
            [("1300", "7800.00", "0.00"), ("2960", "0.00", "7800.00")],
        ),
        (
            GroupContributionRelationship.SISTER_TO_SISTER,
            GroupContributionPerspective.RECIPIENT,
            [("1560", "7800.00", "0.00"), ("2035", "0.00", "7800.00")],
        ),
    ],
)
def test_group_contribution_relationship_selects_distinct_route(
    relationship: GroupContributionRelationship,
    perspective: GroupContributionPerspective,
    expected: list[tuple[str, str, str]],
) -> None:
    persistence = PatternPersistenceStub()

    asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                GroupContributionFacts(
                    relationship=relationship,
                    perspective=perspective,
                    gross_tax_amount=Money.nok("10000.00"),
                    related_tax=Money.nok("2200.00"),
                    after_tax_accounting_amount=Money.nok("7800.00"),
                    post_acquisition_income_proved=(
                        relationship is GroupContributionRelationship.SUBSIDIARY_TO_PARENT
                    ),
                    impairment_cleared=(
                        relationship is GroupContributionRelationship.PARENT_TO_SUBSIDIARY
                    ),
                ),
                source(LedgerSourceCapability.CORPORATE_GOVERNANCE, "group-contribution"),
                source(LedgerSourceCapability.COMPANY_TAX_FILING, "group-contribution-tax"),
            )
        )
    )

    assert posted_lines(persistence) == expected


def test_source_owner_mismatch_blocks_before_persistence() -> None:
    persistence = PatternPersistenceStub()

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).recognize_holding_action(
                command(
                    BankInterestIncomeFacts(amount=Money.nok("500.00")),
                    source(LedgerSourceCapability.CORPORATE_GOVERNANCE, "wrong-owner"),
                )
            )
        )

    assert failure.value.category is ErrorCategory.PRECONDITION_FAILED
    assert failure.value.code == "LEDGER_SOURCE_CAPABILITY_MISMATCH"
    assert persistence.calls == []


def test_fact_variants_never_accept_accounts_lines_or_rule_selection() -> None:
    forbidden = {"account", "accounts", "line", "lines", "pattern", "rule_version"}
    for facts in (
        ApprovedOneSidedIntercompanyLoanFundingFacts,
        BankInterestIncomeFacts,
        CompanyTaxAccrualFacts,
        OrdinaryBankLoanFacts,
        CashCapitalIncreaseFacts,
        ApprovedLossCoverageCapitalReductionFacts,
        ApprovedOwnerLoanFundingFacts,
        GroupContributionFacts,
        InvestmentDividendFacts,
    ):
        assert not (set(facts.__dataclass_fields__) & forbidden)
