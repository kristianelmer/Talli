from __future__ import annotations

import asyncio
from dataclasses import MISSING
from datetime import UTC, date, datetime
from typing import cast

import pytest

from talli_backend.modules.ledger import public as ledger_public
from talli_backend.modules.ledger.public import (
    ApprovedLossCoverageCapitalReductionFacts,
    ApprovedOneSidedIntercompanyLoanFundingFacts,
    ApprovedOwnerLoanFundingFacts,
    BankInterestIncomeFacts,
    BankLoanReferenceId,
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
LOAN_REFERENCE_ID = BankLoanReferenceId("bank-loan:ordinary-facility:1")
CAPITAL_INCREASE_REFERENCE_VALUE = "capital-increase:ordinary-cash:1"
CAPITAL_REDUCTION_REFERENCE_VALUE = "capital-reduction:loss-coverage:1"


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
        decision_reference: object,
        **draft: object,
    ) -> PostedLedgerEntry:
        self.calls.append(
            {
                "operation": "dividend_payment",
                "command": command,
                "decision_reference": decision_reference,
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

    async def record_bank_loan_disbursement(
        self,
        command: object,
        *,
        loan_reference_id: BankLoanReferenceId,
        principal: Money,
        **draft: object,
    ) -> PostedLedgerEntry:
        self.calls.append(
            {
                "operation": "bank_loan_disbursement",
                "command": command,
                "loan_reference_id": loan_reference_id,
                "principal": principal,
                **draft,
            }
        )
        return PostedLedgerEntry(
            entry_id=LedgerEntryId("40000000-0000-0000-0000-000000000007"),
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.BANK_LOAN,
            posted_at=Timestamp(datetime(2026, 8, 27, 10, tzinfo=UTC)),
            replayed=False,
        )

    async def record_bank_loan_payment(
        self,
        command: object,
        *,
        loan_reference_id: BankLoanReferenceId,
        principal: Money,
        interest: Money,
        fee: Money,
        **draft: object,
    ) -> PostedLedgerEntry:
        self.calls.append(
            {
                "operation": "bank_loan_payment",
                "command": command,
                "loan_reference_id": loan_reference_id,
                "principal": principal,
                "interest": interest,
                "fee": fee,
                **draft,
            }
        )
        return PostedLedgerEntry(
            entry_id=LedgerEntryId("40000000-0000-0000-0000-000000000008"),
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.BANK_LOAN,
            posted_at=Timestamp(datetime(2026, 8, 27, 10, tzinfo=UTC)),
            replayed=False,
        )

    async def record_cash_capital_increase_subscription(
        self,
        command: object,
        *,
        capital_increase_reference_id: object,
        nominal_increase: Money,
        share_premium: Money,
        **draft: object,
    ) -> PostedLedgerEntry:
        return self._record_cash_capital_increase(
            "cash_capital_subscription",
            command,
            capital_increase_reference_id=capital_increase_reference_id,
            nominal_increase=nominal_increase,
            share_premium=share_premium,
            **draft,
        )

    async def record_cash_capital_increase_restricted_payment(
        self,
        command: object,
        *,
        capital_increase_reference_id: object,
        nominal_increase: Money,
        share_premium: Money,
        **draft: object,
    ) -> PostedLedgerEntry:
        return self._record_cash_capital_increase(
            "cash_capital_restricted_payment",
            command,
            capital_increase_reference_id=capital_increase_reference_id,
            nominal_increase=nominal_increase,
            share_premium=share_premium,
            **draft,
        )

    async def record_cash_capital_increase_registration(
        self,
        command: object,
        *,
        capital_increase_reference_id: object,
        nominal_increase: Money,
        share_premium: Money,
        **draft: object,
    ) -> PostedLedgerEntry:
        return self._record_cash_capital_increase(
            "cash_capital_registration",
            command,
            capital_increase_reference_id=capital_increase_reference_id,
            nominal_increase=nominal_increase,
            share_premium=share_premium,
            **draft,
        )

    def _record_cash_capital_increase(
        self,
        operation: str,
        command: object,
        **draft: object,
    ) -> PostedLedgerEntry:
        self.calls.append({"operation": operation, "command": command, **draft})
        return PostedLedgerEntry(
            entry_id=LedgerEntryId("40000000-0000-0000-0000-000000000009"),
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.CAPITAL_INCREASE,
            posted_at=Timestamp(datetime(2026, 8, 27, 10, tzinfo=UTC)),
            replayed=False,
        )

    async def record_loss_coverage_capital_reduction_decision(
        self,
        command: object,
        *,
        capital_reduction_reference_id: object,
        nominal_reduction: Money,
        **draft: object,
    ) -> PostedLedgerEntry:
        return self._record_loss_coverage_capital_reduction(
            "capital_reduction_decision",
            command,
            capital_reduction_reference_id=capital_reduction_reference_id,
            nominal_reduction=nominal_reduction,
            **draft,
        )

    async def record_loss_coverage_capital_reduction_registration(
        self,
        command: object,
        *,
        capital_reduction_reference_id: object,
        nominal_reduction: Money,
        **draft: object,
    ) -> PostedLedgerEntry:
        return self._record_loss_coverage_capital_reduction(
            "capital_reduction_registration",
            command,
            capital_reduction_reference_id=capital_reduction_reference_id,
            nominal_reduction=nominal_reduction,
            **draft,
        )

    async def record_loss_coverage_capital_reduction_direct_registration(
        self,
        command: object,
        *,
        capital_reduction_reference_id: object,
        nominal_reduction: Money,
        **draft: object,
    ) -> PostedLedgerEntry:
        return self._record_loss_coverage_capital_reduction(
            "capital_reduction_direct_registration",
            command,
            capital_reduction_reference_id=capital_reduction_reference_id,
            nominal_reduction=nominal_reduction,
            **draft,
        )

    def _record_loss_coverage_capital_reduction(
        self,
        operation: str,
        command: object,
        **draft: object,
    ) -> PostedLedgerEntry:
        self.calls.append({"operation": operation, "command": command, **draft})
        return PostedLedgerEntry(
            entry_id=LedgerEntryId("40000000-0000-0000-0000-000000000010"),
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.CAPITAL_REDUCTION,
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
    fields: dict[str, object] = {
        "recognition": recognition,
        "nominal_reduction": nominal_reduction,
    }
    if (
        "capital_reduction_reference_id"
        in ApprovedLossCoverageCapitalReductionFacts.__dataclass_fields__
    ):
        fields["capital_reduction_reference_id"] = capital_reduction_reference_id()
    return ApprovedLossCoverageCapitalReductionFacts(**fields)  # type: ignore[arg-type]


def capital_reduction_reference_id() -> object:
    reference_type = getattr(
        ledger_public,
        "CapitalReductionReferenceId",
        LedgerSourceRecordId,
    )
    return reference_type(CAPITAL_REDUCTION_REFERENCE_VALUE)


def registered_capital_reduction_recognition() -> CapitalReductionRecognition:
    return getattr(
        CapitalReductionRecognition,
        "REGISTERED",
        cast(CapitalReductionRecognition, "REGISTERED"),
    )


def capital_reduction_sources(
    recognition: CapitalReductionRecognition,
) -> tuple[LedgerFactReference, tuple[LedgerFactReference, ...]]:
    corroborating = [
        source(LedgerSourceCapability.DOCUMENTS, "capital-reduction-documents"),
    ]
    if recognition is not CapitalReductionRecognition.DECIDED_NOT_REGISTERED:
        corroborating.append(
            source(
                LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING,
                "capital-reduction-shareholder-register",
            )
        )
    return (
        source(
            LedgerSourceCapability.CORPORATE_GOVERNANCE,
            "capital-reduction-governance",
        ),
        tuple(corroborating),
    )


def bank_loan_facts(
    *,
    event: BankLoanEvent,
    principal: str,
    interest: str = "0.00",
    fee: str = "0.00",
) -> OrdinaryBankLoanFacts:
    fields: dict[str, object] = {
        "event": event,
        "principal": Money.nok(principal),
        "interest": Money.nok(interest),
        "fee": Money.nok(fee),
    }
    if "loan_reference_id" in OrdinaryBankLoanFacts.__dataclass_fields__:
        fields["loan_reference_id"] = LOAN_REFERENCE_ID
    return OrdinaryBankLoanFacts(**fields)  # type: ignore[arg-type]


def capital_increase_reference_id() -> object:
    reference_type = getattr(
        ledger_public,
        "CapitalIncreaseReferenceId",
        LedgerSourceRecordId,
    )
    return reference_type(CAPITAL_INCREASE_REFERENCE_VALUE)


def cash_capital_increase_facts(
    *,
    phase: CapitalIncreasePhase,
    nominal_increase: str = "10000.00",
    share_premium: str = "5000.00",
) -> CashCapitalIncreaseFacts:
    fields: dict[str, object] = {
        "phase": phase,
        "nominal_increase": Money.nok(nominal_increase),
        "share_premium": Money.nok(share_premium),
    }
    if "capital_increase_reference_id" in CashCapitalIncreaseFacts.__dataclass_fields__:
        fields["capital_increase_reference_id"] = capital_increase_reference_id()
    return CashCapitalIncreaseFacts(**fields)  # type: ignore[arg-type]


def cash_capital_increase_sources(
    phase: CapitalIncreasePhase,
) -> tuple[LedgerFactReference, tuple[LedgerFactReference, ...]]:
    primary = source(
        LedgerSourceCapability.CORPORATE_GOVERNANCE,
        f"capital-{phase.value.lower()}-governance",
    )
    if phase is CapitalIncreasePhase.BINDING_SUBSCRIPTION:
        corroborating = (
            source(LedgerSourceCapability.DOCUMENTS, "capital-subscription-documents"),
        )
    elif phase is CapitalIncreasePhase.RESTRICTED_PAYMENT:
        corroborating = (
            source(LedgerSourceCapability.BANKING, "capital-restricted-bank"),
            source(LedgerSourceCapability.DOCUMENTS, "capital-payment-confirmation"),
        )
    else:
        corroborating = (
            source(LedgerSourceCapability.BANKING, "capital-released-bank"),
            source(LedgerSourceCapability.DOCUMENTS, "capital-registration-documents"),
            source(
                LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING,
                "capital-shareholder-register",
            ),
        )
    return primary, corroborating


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
    assert persistence.calls[0]["decision_reference"] == decision_entry_id
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


def test_bank_loan_public_facts_use_a_required_cross_year_stable_reference() -> None:
    fields = OrdinaryBankLoanFacts.__dataclass_fields__

    assert set(fields) == {
        "event",
        "loan_reference_id",
        "principal",
        "interest",
        "fee",
    }
    assert fields["loan_reference_id"].default is MISSING


def test_bank_loan_disbursement_posts_principal_through_its_lifecycle_port() -> None:
    persistence = PatternPersistenceStub()

    result = asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                bank_loan_facts(
                    event=BankLoanEvent.DISBURSEMENT,
                    principal="50000.00",
                ),
                source(LedgerSourceCapability.BANKING, "bank-loan-disbursement"),
                source(LedgerSourceCapability.DOCUMENTS, "bank-loan-agreement"),
            )
        )
    )

    assert result.entry_kind is LedgerEntryKind.BANK_LOAN
    assert persistence.calls[0]["operation"] == "bank_loan_disbursement"
    assert persistence.calls[0]["loan_reference_id"] == LOAN_REFERENCE_ID
    assert persistence.calls[0]["principal"] == Money.nok("50000.00")
    assert posted_lines(persistence) == [
        ("1920", "50000.00", "0.00"),
        ("2220", "0.00", "50000.00"),
    ]


def test_bank_loan_payment_separates_allocation_through_its_lifecycle_port() -> None:
    persistence = PatternPersistenceStub()

    result = asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                bank_loan_facts(
                    event=BankLoanEvent.PAYMENT,
                    principal="10000.00",
                    interest="2000.00",
                    fee="100.00",
                ),
                source(LedgerSourceCapability.BANKING, "bank-loan-payment"),
                source(LedgerSourceCapability.DOCUMENTS, "bank-loan-statement"),
            )
        )
    )

    assert result.entry_kind is LedgerEntryKind.BANK_LOAN
    assert persistence.calls[0]["operation"] == "bank_loan_payment"
    assert persistence.calls[0]["loan_reference_id"] == LOAN_REFERENCE_ID
    assert persistence.calls[0]["principal"] == Money.nok("10000.00")
    assert persistence.calls[0]["interest"] == Money.nok("2000.00")
    assert persistence.calls[0]["fee"] == Money.nok("100.00")
    assert posted_lines(persistence) == [
        ("2220", "10000.00", "0.00"),
        ("8150", "2000.00", "0.00"),
        ("7770", "100.00", "0.00"),
        ("1920", "0.00", "12100.00"),
    ]


def test_bank_loan_payment_omits_zero_allocation_lines() -> None:
    persistence = PatternPersistenceStub()

    asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                bank_loan_facts(
                    event=BankLoanEvent.PAYMENT,
                    principal="0.00",
                    interest="200.00",
                    fee="0.00",
                ),
                source(LedgerSourceCapability.BANKING, "bank-loan-interest-payment"),
                source(LedgerSourceCapability.DOCUMENTS, "bank-loan-interest-statement"),
            )
        )
    )

    assert posted_lines(persistence) == [
        ("8150", "200.00", "0.00"),
        ("1920", "0.00", "200.00"),
    ]


@pytest.mark.parametrize(
    ("facts", "primary", "corroborating"),
    [
        (
            bank_loan_facts(event=BankLoanEvent.DISBURSEMENT, principal="50000.00"),
            source(LedgerSourceCapability.BANKING, "bank-loan-missing-document"),
            (),
        ),
        (
            bank_loan_facts(event=BankLoanEvent.PAYMENT, principal="1000.00"),
            source(LedgerSourceCapability.DOCUMENTS, "bank-loan-wrong-primary"),
            (source(LedgerSourceCapability.BANKING, "bank-loan-bank-corroboration"),),
        ),
        (
            bank_loan_facts(event=BankLoanEvent.PAYMENT, principal="1000.00"),
            source(LedgerSourceCapability.BANKING, "bank-loan-extra-source"),
            (
                source(LedgerSourceCapability.DOCUMENTS, "bank-loan-document"),
                source(LedgerSourceCapability.CORPORATE_GOVERNANCE, "bank-loan-extra"),
            ),
        ),
        (
            bank_loan_facts(event=BankLoanEvent.DISBURSEMENT, principal="50000.00"),
            source(LedgerSourceCapability.BANKING, "bank-loan-duplicate-document"),
            (
                source(LedgerSourceCapability.DOCUMENTS, "bank-loan-document-one"),
                source(LedgerSourceCapability.DOCUMENTS, "bank-loan-document-two"),
            ),
        ),
    ],
)
def test_bank_loan_requires_exact_banking_primary_and_document_corroboration(
    facts: OrdinaryBankLoanFacts,
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


def test_bank_loan_rejects_runtime_invalid_phase_without_persistence() -> None:
    persistence = PatternPersistenceStub()
    facts = bank_loan_facts(
        event=cast(BankLoanEvent, "UNSUPPORTED"),
        principal="1000.00",
    )

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).recognize_holding_action(
                command(
                    facts,
                    source(LedgerSourceCapability.BANKING, "bank-loan-invalid-phase"),
                    source(LedgerSourceCapability.DOCUMENTS, "bank-loan-invalid-document"),
                )
            )
        )

    assert failure.value.code == "LEDGER_INVALID_INPUT"
    assert persistence.calls == []


@pytest.mark.parametrize(
    "facts",
    [
        bank_loan_facts(event=BankLoanEvent.DISBURSEMENT, principal="0.00"),
        bank_loan_facts(
            event=BankLoanEvent.DISBURSEMENT,
            principal="50000.00",
            interest="1.00",
        ),
        bank_loan_facts(
            event=BankLoanEvent.DISBURSEMENT,
            principal="50000.00",
            fee="1.00",
        ),
        bank_loan_facts(event=BankLoanEvent.PAYMENT, principal="-1.00"),
        bank_loan_facts(
            event=BankLoanEvent.PAYMENT,
            principal="0.00",
            interest="-1.00",
        ),
        bank_loan_facts(
            event=BankLoanEvent.PAYMENT,
            principal="0.00",
            fee="-1.00",
        ),
        bank_loan_facts(event=BankLoanEvent.PAYMENT, principal="0.00"),
    ],
)
def test_bank_loan_rejects_invalid_numeric_allocations_before_persistence(
    facts: OrdinaryBankLoanFacts,
) -> None:
    persistence = PatternPersistenceStub()

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).recognize_holding_action(
                command(
                    facts,
                    source(LedgerSourceCapability.BANKING, "bank-loan-invalid-amount"),
                    source(LedgerSourceCapability.DOCUMENTS, "bank-loan-invalid-evidence"),
                )
            )
        )

    assert failure.value.code == "LEDGER_INVALID_INPUT"
    assert persistence.calls == []


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


def test_cash_capital_increase_has_a_stable_lifecycle_reference() -> None:
    reference_type = getattr(ledger_public, "CapitalIncreaseReferenceId", None)

    assert reference_type is not None
    assert "capital_increase_reference_id" in CashCapitalIncreaseFacts.__dataclass_fields__
    assert str(reference_type(f"  {CAPITAL_INCREASE_REFERENCE_VALUE}  ")) == (
        CAPITAL_INCREASE_REFERENCE_VALUE
    )
    for invalid in ("", "   ", "x" * 256):
        with pytest.raises(ValueError):
            reference_type(invalid)


@pytest.mark.parametrize(
    ("phase", "operation", "expected"),
    [
        (
            CapitalIncreasePhase.BINDING_SUBSCRIPTION,
            "cash_capital_subscription",
            [("1500", "15000.00", "0.00"), ("2030", "0.00", "15000.00")],
        ),
        (
            CapitalIncreasePhase.RESTRICTED_PAYMENT,
            "cash_capital_restricted_payment",
            [("1921", "15000.00", "0.00"), ("1500", "0.00", "15000.00")],
        ),
        (
            CapitalIncreasePhase.REGISTERED,
            "cash_capital_registration",
            [
                ("2030", "15000.00", "0.00"),
                ("2000", "0.00", "10000.00"),
                ("2020", "0.00", "5000.00"),
                ("1920", "15000.00", "0.00"),
                ("1921", "0.00", "15000.00"),
            ],
        ),
    ],
)
def test_cash_capital_increase_phases_use_exact_sources_journals_and_lifecycle_ports(
    phase: CapitalIncreasePhase,
    operation: str,
    expected: list[tuple[str, str, str]],
) -> None:
    persistence = PatternPersistenceStub()
    primary, corroborating = cash_capital_increase_sources(phase)

    asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                cash_capital_increase_facts(phase=phase),
                primary,
                *corroborating,
            )
        )
    )

    assert posted_lines(persistence) == expected
    assert persistence.calls[0]["operation"] == operation
    assert str(persistence.calls[0]["capital_increase_reference_id"]) == (
        CAPITAL_INCREASE_REFERENCE_VALUE
    )
    assert persistence.calls[0]["nominal_increase"] == Money.nok("10000.00")
    assert persistence.calls[0]["share_premium"] == Money.nok("5000.00")


def test_registered_cash_capital_omits_a_zero_share_premium_line() -> None:
    persistence = PatternPersistenceStub()
    primary, corroborating = cash_capital_increase_sources(
        CapitalIncreasePhase.REGISTERED
    )

    asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                cash_capital_increase_facts(
                    phase=CapitalIncreasePhase.REGISTERED,
                    share_premium="0.00",
                ),
                primary,
                *corroborating,
            )
        )
    )

    assert posted_lines(persistence) == [
        ("2030", "10000.00", "0.00"),
        ("2000", "0.00", "10000.00"),
        ("1920", "10000.00", "0.00"),
        ("1921", "0.00", "10000.00"),
    ]


@pytest.mark.parametrize("phase", list(CapitalIncreasePhase))
def test_cash_capital_increase_rejects_an_incomplete_phase_source_topology(
    phase: CapitalIncreasePhase,
) -> None:
    persistence = PatternPersistenceStub()
    primary, corroborating = cash_capital_increase_sources(phase)

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).recognize_holding_action(
                command(
                    cash_capital_increase_facts(phase=phase),
                    primary,
                    *corroborating[:-1],
                )
            )
        )

    assert failure.value.code == "LEDGER_SOURCE_CAPABILITY_MISMATCH"
    assert persistence.calls == []


def test_cash_capital_increase_rejects_an_unknown_runtime_phase() -> None:
    persistence = PatternPersistenceStub()

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).recognize_holding_action(
                command(
                    cash_capital_increase_facts(
                        phase=cast(CapitalIncreasePhase, "UNSUPPORTED_PHASE")
                    ),
                    source(
                        LedgerSourceCapability.CORPORATE_GOVERNANCE,
                        "capital-unsupported-phase",
                    ),
                )
            )
        )

    assert failure.value.code == "LEDGER_INVALID_INPUT"
    assert persistence.calls == []


@pytest.mark.parametrize(
    ("nominal_increase", "share_premium"),
    [
        ("0.00", "5000.00"),
        ("-1.00", "5000.00"),
        ("10000.00", "-1.00"),
    ],
)
def test_cash_capital_increase_rejects_invalid_amounts_before_persistence(
    nominal_increase: str,
    share_premium: str,
) -> None:
    persistence = PatternPersistenceStub()

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).recognize_holding_action(
                command(
                    cash_capital_increase_facts(
                        phase=CapitalIncreasePhase.BINDING_SUBSCRIPTION,
                        nominal_increase=nominal_increase,
                        share_premium=share_premium,
                    ),
                    source(
                        LedgerSourceCapability.CORPORATE_GOVERNANCE,
                        "capital-invalid-amount",
                    ),
                )
            )
        )

    assert failure.value.code == "LEDGER_INVALID_INPUT"
    assert persistence.calls == []


def test_loss_coverage_capital_reduction_has_a_stable_lifecycle_reference() -> None:
    reference_type = getattr(ledger_public, "CapitalReductionReferenceId", None)

    assert reference_type is not None
    assert (
        "capital_reduction_reference_id"
        in ApprovedLossCoverageCapitalReductionFacts.__dataclass_fields__
    )
    assert str(reference_type(f"  {CAPITAL_REDUCTION_REFERENCE_VALUE}  ")) == (
        CAPITAL_REDUCTION_REFERENCE_VALUE
    )
    for invalid in ("", "   ", "x" * 256):
        with pytest.raises(ValueError):
            reference_type(invalid)


@pytest.mark.parametrize(
    ("recognition", "operation", "expected"),
    [
        (
            CapitalReductionRecognition.DECIDED_NOT_REGISTERED,
            "capital_reduction_decision",
            [("2033", "20000.00", "0.00"), ("2080", "0.00", "20000.00")],
        ),
        (
            registered_capital_reduction_recognition(),
            "capital_reduction_registration",
            [("2000", "20000.00", "0.00"), ("2033", "0.00", "20000.00")],
        ),
        (
            CapitalReductionRecognition.FIRST_RECOGNIZED_AFTER_REGISTRATION,
            "capital_reduction_direct_registration",
            [("2000", "20000.00", "0.00"), ("2080", "0.00", "20000.00")],
        ),
    ],
)
def test_loss_coverage_capital_reduction_phases_use_exact_sources_journals_and_ports(
    recognition: CapitalReductionRecognition,
    operation: str,
    expected: list[tuple[str, str, str]],
) -> None:
    persistence = PatternPersistenceStub()
    primary, corroborating = capital_reduction_sources(recognition)

    asyncio.run(
        LedgerService(persistence).recognize_holding_action(
            command(
                capital_reduction_facts(recognition=recognition),
                primary,
                *corroborating,
            )
        )
    )

    assert posted_lines(persistence) == expected
    assert persistence.calls[0]["operation"] == operation
    assert str(persistence.calls[0]["capital_reduction_reference_id"]) == (
        CAPITAL_REDUCTION_REFERENCE_VALUE
    )
    assert persistence.calls[0]["nominal_reduction"] == Money.nok("20000.00")


@pytest.mark.parametrize(
    "recognition",
    [
        CapitalReductionRecognition.DECIDED_NOT_REGISTERED,
        registered_capital_reduction_recognition(),
        CapitalReductionRecognition.FIRST_RECOGNIZED_AFTER_REGISTRATION,
    ],
)
def test_loss_coverage_capital_reduction_requires_exact_phase_source_topology(
    recognition: CapitalReductionRecognition,
) -> None:
    persistence = PatternPersistenceStub()
    primary, corroborating = capital_reduction_sources(recognition)

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).recognize_holding_action(
                command(
                    capital_reduction_facts(recognition=recognition),
                    primary,
                    *corroborating[:-1],
                )
            )
        )

    assert failure.value.code == "LEDGER_SOURCE_CAPABILITY_MISMATCH"
    assert persistence.calls == []


def test_loss_coverage_capital_reduction_rejects_an_unknown_runtime_phase() -> None:
    persistence = PatternPersistenceStub()

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).recognize_holding_action(
                command(
                    capital_reduction_facts(
                        recognition=cast(CapitalReductionRecognition, "UNSUPPORTED")
                    ),
                    source(
                        LedgerSourceCapability.CORPORATE_GOVERNANCE,
                        "capital-reduction-unsupported-phase",
                    ),
                    source(
                        LedgerSourceCapability.DOCUMENTS,
                        "capital-reduction-unsupported-documents",
                    ),
                    source(
                        LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING,
                        "capital-reduction-unsupported-shareholder-register",
                    ),
                )
            )
        )

    assert failure.value.code == "LEDGER_INVALID_INPUT"
    assert persistence.calls == []


@pytest.mark.parametrize("nominal_reduction", ["0.00", "-1.00"])
def test_loss_coverage_capital_reduction_rejects_invalid_amount_before_persistence(
    nominal_reduction: str,
) -> None:
    persistence = PatternPersistenceStub()
    recognition = CapitalReductionRecognition.DECIDED_NOT_REGISTERED
    primary, corroborating = capital_reduction_sources(recognition)

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).recognize_holding_action(
                command(
                    capital_reduction_facts(
                        recognition=recognition,
                        nominal_reduction=Money.nok(nominal_reduction),
                    ),
                    primary,
                    *corroborating,
                )
            )
        )

    assert failure.value.code == "LEDGER_INVALID_INPUT"
    assert persistence.calls == []


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
