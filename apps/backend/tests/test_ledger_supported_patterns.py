from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from talli_backend.modules.ledger.public import (
    BankInterestIncomeFacts,
    BankLoanEvent,
    CashCapitalIncreaseFacts,
    CapitalIncreasePhase,
    CompanyTaxAccrualFacts,
    GroupContributionFacts,
    GroupContributionPerspective,
    GroupContributionRelationship,
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
        ("2005", "15000.00", "0.00"),
        ("2000", "0.00", "10000.00"),
        ("2020", "0.00", "5000.00"),
        ("1920", "15000.00", "0.00"),
        ("1950", "0.00", "15000.00"),
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
            [("1560", "7800.00", "0.00"), ("2030", "0.00", "7800.00")],
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
        BankInterestIncomeFacts,
        CompanyTaxAccrualFacts,
        OrdinaryBankLoanFacts,
        CashCapitalIncreaseFacts,
        GroupContributionFacts,
    ):
        assert not (set(facts.__dataclass_fields__) & forbidden)
