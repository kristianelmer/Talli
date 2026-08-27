from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from talli_backend.modules.ledger.public import (
    AdministrativeCostCategory,
    BankSuggestionRule,
    LedgerEntryId,
    LedgerEntryKind,
    LedgerEntryPage,
    LedgerError,
    LedgerLine,
    LedgerPage,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    LockPeriodCommand,
    PeriodLock,
    PeriodLockId,
    PeriodLockPage,
    PostBankSuggestionOutcomeCommand,
    PostInvestmentDividendCommand,
    PostInvestmentPurchaseCommand,
    PostInvestmentSaleCommand,
    PostAdministrativeCostCommand,
    PostedLedgerEntry,
    PostManualJournalCommand,
    PostOpeningBalanceCommand,
    PostOwnerDividendDeclaredCommand,
    PostOwnerDividendPaymentCommand,
    PostShareholderLoanCommand,
    PostTaxSettlementCommand,
    ShareholderLoanDirection,
    TaxSettlementKind,
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
CORRELATION_ID = CorrelationId("ledger-service-test")
IDEMPOTENCY_KEY = IdempotencyKey("30000000-0000-4000-8000-000000000003")
INCOME_YEAR = IncomeYear(2026)
ENTRY_ID = LedgerEntryId("40000000-0000-0000-0000-000000000004")
NOW = Timestamp(datetime(2026, 8, 27, 10, tzinfo=UTC))


def metadata() -> dict[str, object]:
    return {
        "company_id": COMPANY_ID,
        "actor_id": ACTOR_ID,
        "correlation_id": CORRELATION_ID,
        "idempotency_key": IDEMPOTENCY_KEY,
        "income_year": INCOME_YEAR,
    }


class LedgerPersistenceStub:
    def __init__(self) -> None:
        self.postings: list[dict[str, object]] = []

    async def post_entry(self, command: object, **posting: object) -> PostedLedgerEntry:
        self.postings.append({"command": command, **posting})
        return PostedLedgerEntry(
            entry_id=ENTRY_ID,
            company_id=COMPANY_ID,
            income_year=INCOME_YEAR,
            entry_kind=posting["entry_kind"],
            posted_at=NOW,
            replayed=False,
        )

    async def lock_period(self, command: LockPeriodCommand) -> PeriodLock:
        return PeriodLock(
            period_lock_id=PeriodLockId("50000000-0000-0000-0000-000000000005"),
            company_id=command.company_id,
            income_year=command.income_year,
            reason=command.reason,
            locked_by=command.actor_id,
            locked_at=NOW,
            replayed=False,
        )

    async def list_entries(self, **_query: object) -> LedgerEntryPage:
        return LedgerEntryPage(items=(), page=LedgerPage(next_cursor=None, has_more=False))

    async def list_period_locks(self, **_query: object) -> PeriodLockPage:
        return PeriodLockPage(items=(), page=LedgerPage(next_cursor=None, has_more=False))


def test_opening_balance_preserves_the_frozen_typescript_posting() -> None:
    persistence = LedgerPersistenceStub()
    command = PostOpeningBalanceCommand(
        **metadata(),
        bank_balance=Money.nok("30000.00"),
        share_capital_snapshot=Money.nok("30000.00"),
    )

    result = asyncio.run(LedgerService(persistence).post_opening_balance(command))

    assert result.entry_id == ENTRY_ID
    assert persistence.postings[0]["entry_kind"] is LedgerEntryKind.OPENING_BALANCE
    assert persistence.postings[0]["lines"] == (
        LedgerLine("1920", "Bankinnskudd", Money.nok("30000"), Money.nok("0")),
        LedgerLine("2000", "Aksjekapital", Money.nok("0"), Money.nok("30000")),
        LedgerLine("2050", "Annen egenkapital", Money.nok("0"), Money.nok("0")),
    )


def test_opening_balance_keeps_the_legacy_uncovered_loss_shape() -> None:
    persistence = LedgerPersistenceStub()
    command = PostOpeningBalanceCommand(
        **metadata(),
        bank_balance=Money.nok("20000"),
        share_capital_snapshot=Money.nok("30000"),
    )

    asyncio.run(LedgerService(persistence).post_opening_balance(command))

    assert persistence.postings[0]["lines"][-1] == LedgerLine(
        "2050", "Udekket tap", Money.nok("10000"), Money.nok("0")
    )


def test_opening_balance_can_correlate_to_shareholder_register_snapshot() -> None:
    persistence = LedgerPersistenceStub()
    opening_snapshot_id = LedgerSourceRecordId(
        "61000000-0000-0000-0000-000000000006"
    )
    command = PostOpeningBalanceCommand(
        **metadata(),
        bank_balance=Money.nok("30000"),
        share_capital_snapshot=Money.nok("30000"),
        opening_snapshot_id=opening_snapshot_id,
    )

    asyncio.run(LedgerService(persistence).post_opening_balance(command))

    assert (
        persistence.postings[0]["source_capability"]
        is LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING
    )
    assert persistence.postings[0]["source_record_id"] == opening_snapshot_id


def test_manual_journal_enforces_balance_and_exact_sensitive_account_set() -> None:
    persistence = LedgerPersistenceStub()
    sensitive = PostManualJournalCommand(
        **metadata(),
        memo=" Sensitive correction ",
        warning_accepted=True,
        lines=(
            LedgerLine("1800", "Investment", Money.nok("100.005"), Money.nok("0")),
            LedgerLine("1920", "Bank", Money.nok("0"), Money.nok("100.005")),
        ),
    )
    asyncio.run(LedgerService(persistence).post_manual_journal(sensitive))

    flags = persistence.postings[0]["risk_flags"]
    assert [(flag.code.value, flag.account) for flag in flags] == [
        ("MANUAL_JOURNAL_SENSITIVE_ACCOUNT", "1800")
    ]
    assert persistence.postings[0]["memo"] == "Sensitive correction"

    with pytest.raises(LedgerError) as failure:
        asyncio.run(
            LedgerService(persistence).post_manual_journal(
                PostManualJournalCommand(
                    **metadata(),
                    memo="Unbalanced",
                    warning_accepted=False,
                    lines=(
                        LedgerLine("7795", "Cost", Money.nok("100"), Money.nok("0")),
                        LedgerLine("1920", "Bank", Money.nok("0"), Money.nok("99")),
                    ),
                )
            )
        )
    assert failure.value.code == "LEDGER_ENTRY_UNBALANCED"
    assert failure.value.category is ErrorCategory.INVALID_INPUT


def test_manual_warning_must_be_explicitly_accepted() -> None:
    persistence = LedgerPersistenceStub()
    command = PostManualJournalCommand(
        **metadata(),
        memo="Sensitive correction",
        warning_accepted=False,
        lines=(
            LedgerLine("2050", "Equity", Money.nok("100"), Money.nok("0")),
            LedgerLine("1920", "Bank", Money.nok("0"), Money.nok("100")),
        ),
    )

    with pytest.raises(LedgerError) as failure:
        asyncio.run(LedgerService(persistence).post_manual_journal(command))
    assert failure.value.code == "LEDGER_WARNING_ACCEPTANCE_REQUIRED"
    assert failure.value.category is ErrorCategory.PRECONDITION_FAILED
    assert persistence.postings == []


@pytest.mark.parametrize(
    ("category", "account"),
    [
        (AdministrativeCostCategory.BANK_FEE, "7770"),
        (AdministrativeCostCategory.ACCOUNTING_FEE, "6705"),
        (AdministrativeCostCategory.SOFTWARE, "6420"),
        (AdministrativeCostCategory.PUBLIC_FEE, "7790"),
        (AdministrativeCostCategory.LEGAL_ADVISORY, "6720"),
        (AdministrativeCostCategory.OTHER_ADMIN_COST, "7795"),
    ],
)
def test_administrative_cost_policy_is_python_owned(
    category: AdministrativeCostCategory,
    account: str,
) -> None:
    persistence = LedgerPersistenceStub()
    command = PostAdministrativeCostCommand(
        **metadata(),
        bank_transaction_id=LedgerSourceRecordId("60000000-0000-0000-0000-000000000006"),
        category=category,
        payee="Talli AS",
        amount=Money.nok("1490"),
        paid_date=LocalDate(date(2026, 8, 27)),
    )

    asyncio.run(LedgerService(persistence).post_administrative_cost(command))

    assert persistence.postings[0]["source_capability"] is LedgerSourceCapability.BANKING
    assert persistence.postings[0]["lines"] == (
        LedgerLine(account, "Admin cost: Talli AS", Money.nok("1490"), Money.nok("0")),
        LedgerLine("1920", "Paid from bank", Money.nok("0"), Money.nok("1490")),
    )


def test_administrative_cost_rejects_a_date_outside_the_company_year() -> None:
    persistence = LedgerPersistenceStub()
    command = PostAdministrativeCostCommand(
        **metadata(),
        bank_transaction_id=LedgerSourceRecordId(
            "60000000-0000-0000-0000-000000000006"
        ),
        category=AdministrativeCostCategory.BANK_FEE,
        payee="Talli AS",
        amount=Money.nok("1490"),
        paid_date=LocalDate(date(2025, 12, 31)),
    )

    with pytest.raises(LedgerError) as failure:
        asyncio.run(LedgerService(persistence).post_administrative_cost(command))
    assert failure.value.code == "LEDGER_INVALID_INPUT"
    assert persistence.postings == []


@pytest.mark.parametrize(
    ("rule", "amount", "expected_lines"),
    [
        (
            BankSuggestionRule.BANK_FEE,
            Money.nok("89"),
            (
                LedgerLine("7770", "Bankomkostninger", Money.nok("89"), Money.nok("0")),
                LedgerLine("1920", "Bank", Money.nok("0"), Money.nok("89")),
            ),
        ),
        (
            BankSuggestionRule.SYSTEM_SUBSCRIPTION,
            Money.nok("1490"),
            (
                LedgerLine("6700", "Fremmede tjenester", Money.nok("1490"), Money.nok("0")),
                LedgerLine("1920", "Bank", Money.nok("0"), Money.nok("1490")),
            ),
        ),
        (
            BankSuggestionRule.DEPOSIT_INTEREST,
            Money.nok("12.50"),
            (
                LedgerLine("1920", "Bank", Money.nok("12.50"), Money.nok("0")),
                LedgerLine("8050", "Annen renteinntekt", Money.nok("0"), Money.nok("12.50")),
            ),
        ),
    ],
)
def test_accepted_bank_suggestion_translates_authoritative_rule_to_ledger_policy(
    rule: BankSuggestionRule,
    amount: Money,
    expected_lines: tuple[LedgerLine, ...],
) -> None:
    persistence = LedgerPersistenceStub()
    command = PostBankSuggestionOutcomeCommand(
        **metadata(),
        acceptance_id=LedgerSourceRecordId("70000000-0000-0000-0000-000000000007"),
        rule=rule,
        amount=amount,
        transaction_text=" Årsgebyr ",
    )

    asyncio.run(LedgerService(persistence).post_bank_suggestion_outcome(command))

    assert persistence.postings[0]["entry_kind"] is LedgerEntryKind.BANK_RULE_SUGGESTION
    assert persistence.postings[0]["source_capability"] is LedgerSourceCapability.BANKING
    assert persistence.postings[0]["source_record_id"] == command.acceptance_id
    assert persistence.postings[0]["memo"] == "Godkjent bankforslag: Årsgebyr"
    assert persistence.postings[0]["lines"] == expected_lines


def test_received_dividend_translates_investment_facts_without_source_lines() -> None:
    persistence = LedgerPersistenceStub()
    command = PostInvestmentDividendCommand(
        **metadata(),
        action_id=LedgerSourceRecordId("72000000-0000-0000-0000-000000000007"),
        paying_company_name=" Eksempel Invest AS ",
        gross_amount=Money.nok("12500"),
    )

    asyncio.run(LedgerService(persistence).post_investment_dividend(command))

    assert persistence.postings[0]["entry_kind"] is LedgerEntryKind.DIVIDEND_RECEIVED
    assert persistence.postings[0]["source_capability"] is LedgerSourceCapability.INVESTMENTS
    assert persistence.postings[0]["source_record_id"] == command.action_id
    assert persistence.postings[0]["memo"] == "Dividend received from Eksempel Invest AS"
    assert persistence.postings[0]["lines"] == (
        LedgerLine("1920", "Dividend received in bank", Money.nok("12500"), Money.nok("0")),
        LedgerLine("8070", "Dividend from Eksempel Invest AS", Money.nok("0"), Money.nok("12500")),
    )


def test_share_purchase_translates_authoritative_investment_result() -> None:
    persistence = LedgerPersistenceStub()
    command = PostInvestmentPurchaseCommand(
        **metadata(),
        action_id=LedgerSourceRecordId("74000000-0000-0000-0000-000000000007"),
        investment_name=" Eksempel Holding AS ",
        purchase_amount=Money.nok("100000"),
    )

    asyncio.run(LedgerService(persistence).post_investment_purchase(command))

    assert persistence.postings[0]["entry_kind"] is LedgerEntryKind.SHARE_PURCHASE
    assert persistence.postings[0]["source_capability"] is LedgerSourceCapability.INVESTMENTS
    assert persistence.postings[0]["source_record_id"] == command.action_id
    assert persistence.postings[0]["memo"] == "Share purchase: Eksempel Holding AS"
    assert persistence.postings[0]["lines"] == (
        LedgerLine("1800", "Investment in Eksempel Holding AS", Money.nok("100000"), Money.nok("0")),
        LedgerLine("1920", "Paid from bank", Money.nok("0"), Money.nok("100000")),
    )


@pytest.mark.parametrize(
    ("proceeds", "fifo_cost", "result_line"),
    [
        (
            Money.nok("120000"),
            Money.nok("100000"),
            LedgerLine("8070", "Share sale gain: Eksempel Holding AS", Money.nok("0"), Money.nok("20000")),
        ),
        (
            Money.nok("90000"),
            Money.nok("100000"),
            LedgerLine("8090", "Share sale loss: Eksempel Holding AS", Money.nok("10000"), Money.nok("0")),
        ),
        (Money.nok("100000"), Money.nok("100000"), None),
    ],
)
def test_share_sale_uses_provider_authoritative_fifo_cost_result(
    proceeds: Money,
    fifo_cost: Money,
    result_line: LedgerLine | None,
) -> None:
    persistence = LedgerPersistenceStub()
    command = PostInvestmentSaleCommand(
        **metadata(),
        action_id=LedgerSourceRecordId("76000000-0000-0000-0000-000000000007"),
        investment_name="Eksempel Holding AS",
        proceeds=proceeds,
        fifo_cost_basis_reduction=fifo_cost,
    )

    asyncio.run(LedgerService(persistence).post_investment_sale(command))

    expected = (
        LedgerLine("1920", "Sale proceeds received in bank", proceeds, Money.nok("0")),
        LedgerLine("1800", "Cost basis reduction: Eksempel Holding AS", Money.nok("0"), fifo_cost),
    ) + (() if result_line is None else (result_line,))
    assert persistence.postings[0]["entry_kind"] is LedgerEntryKind.SHARE_SALE
    assert persistence.postings[0]["source_capability"] is LedgerSourceCapability.INVESTMENTS
    assert persistence.postings[0]["source_record_id"] == command.action_id
    assert persistence.postings[0]["lines"] == expected


def test_owner_dividend_declaration_uses_the_locked_approved_policy_snapshot() -> None:
    persistence = LedgerPersistenceStub()
    command = PostOwnerDividendDeclaredCommand(
        **metadata(),
        finalization_id=LedgerSourceRecordId(
            "78000000-0000-0000-0000-000000000007"
        ),
        declared_amount=Money.nok("50000"),
        declaration_debit_account="2050",
        dividend_payable_account="2800",
        accounting_policy_version="owner-dividend-v1",
        ledger_entry_id=ENTRY_ID,
    )

    asyncio.run(LedgerService(persistence).post_owner_dividend_declared(command))

    assert persistence.postings[0]["lines"] == (
        LedgerLine("2050", "Declared dividend to owners", Money.nok("50000"), Money.nok("0")),
        LedgerLine("2800", "Dividend payable to owners", Money.nok("0"), Money.nok("50000")),
    )
    assert persistence.postings[0]["requested_entry_id"] == ENTRY_ID


def test_owner_dividend_payment_uses_the_locked_approved_policy_snapshot() -> None:
    persistence = LedgerPersistenceStub()
    command = PostOwnerDividendPaymentCommand(
        **metadata(),
        payment_event_id=LedgerSourceRecordId(
            "80000000-0000-0000-0000-000000000008"
        ),
        payment_amount=Money.nok("25000"),
        dividend_payable_account="2800",
        bank_account="1920",
        accounting_policy_version="owner-dividend-v1",
        ledger_entry_id=ENTRY_ID,
    )

    asyncio.run(LedgerService(persistence).post_owner_dividend_payment(command))

    assert persistence.postings[0]["lines"] == (
        LedgerLine("2800", "Dividend payable cleared", Money.nok("25000"), Money.nok("0")),
        LedgerLine("1920", "Dividend paid from bank", Money.nok("0"), Money.nok("25000")),
    )
    assert persistence.postings[0]["requested_entry_id"] == ENTRY_ID


@pytest.mark.parametrize(
    ("direction", "expected_lines"),
    [
        (
            ShareholderLoanDirection.SHAREHOLDER_TO_COMPANY,
            (
                LedgerLine("1920", "Loan received from Eier AS", Money.nok("40000"), Money.nok("0")),
                LedgerLine("2255", "Loan payable to Eier AS", Money.nok("0"), Money.nok("40000")),
            ),
        ),
        (
            ShareholderLoanDirection.COMPANY_TO_CORPORATE_SHAREHOLDER,
            (
                LedgerLine("1370", "Loan receivable from Eier AS", Money.nok("40000"), Money.nok("0")),
                LedgerLine("1920", "Loan paid to Eier AS", Money.nok("0"), Money.nok("40000")),
            ),
        ),
    ],
)
def test_shareholder_loan_direction_selects_ledger_owned_accounts(
    direction: ShareholderLoanDirection,
    expected_lines: tuple[LedgerLine, ...],
) -> None:
    persistence = LedgerPersistenceStub()
    command = PostShareholderLoanCommand(
        **metadata(),
        action_id=LedgerSourceRecordId("83000000-0000-0000-0000-000000000008"),
        counterparty_name=" Eier AS ",
        direction=direction,
        amount=Money.nok("40000"),
    )

    asyncio.run(LedgerService(persistence).post_shareholder_loan(command))

    assert persistence.postings[0]["entry_kind"] is LedgerEntryKind.SHAREHOLDER_LOAN
    assert persistence.postings[0]["source_capability"] is LedgerSourceCapability.CORPORATE_GOVERNANCE
    assert persistence.postings[0]["source_record_id"] == command.action_id
    assert persistence.postings[0]["memo"] == "Shareholder loan: Eier AS"
    assert persistence.postings[0]["lines"] == expected_lines


@pytest.mark.parametrize(
    ("settlement_kind", "expected_lines"),
    [
        (
            TaxSettlementKind.PAYABLE,
            (
                LedgerLine("8300", "Skattekostnad", Money.nok("22000"), Money.nok("0")),
                LedgerLine("2500", "Betalbar skatt", Money.nok("0"), Money.nok("22000")),
            ),
        ),
        (
            TaxSettlementKind.PAYMENT,
            (
                LedgerLine("2500", "Betalt skatt", Money.nok("22000"), Money.nok("0")),
                LedgerLine("1920", "Bank", Money.nok("0"), Money.nok("22000")),
            ),
        ),
        (
            TaxSettlementKind.REFUND,
            (
                LedgerLine("1920", "Skatterefusjon mottatt", Money.nok("22000"), Money.nok("0")),
                LedgerLine("1570", "Skatt til gode", Money.nok("0"), Money.nok("22000")),
            ),
        ),
    ],
)
def test_tax_settlement_kind_selects_ledger_owned_accounts(
    settlement_kind: TaxSettlementKind,
    expected_lines: tuple[LedgerLine, ...],
) -> None:
    persistence = LedgerPersistenceStub()
    command = PostTaxSettlementCommand(
        **metadata(),
        settlement_id=LedgerSourceRecordId(
            "85000000-0000-0000-0000-000000000008"
        ),
        settlement_kind=settlement_kind,
        amount=Money.nok("22000"),
    )

    asyncio.run(LedgerService(persistence).post_tax_settlement(command))

    assert persistence.postings[0]["entry_kind"] is LedgerEntryKind.TAX_SETTLEMENT
    assert persistence.postings[0]["source_capability"] is LedgerSourceCapability.COMPANY_TAX_FILING
    assert persistence.postings[0]["source_record_id"] == command.settlement_id
    assert persistence.postings[0]["memo"] == f"Skatteoppgjør: {settlement_kind.value}"
    assert persistence.postings[0]["lines"] == expected_lines


def test_lock_and_paginated_queries_are_purpose_specific() -> None:
    persistence = LedgerPersistenceStub()
    service = LedgerService(persistence)
    lock = asyncio.run(
        service.lock_period(LockPeriodCommand(**metadata(), reason=" Filing complete "))
    )
    entries = asyncio.run(
        service.list_entries(
            actor_id=ACTOR_ID,
            company_ids=(COMPANY_ID,),
            correlation_id=CORRELATION_ID,
            cursor=None,
            limit=50,
        )
    )

    assert lock.reason == " Filing complete "
    assert entries == LedgerEntryPage(
        items=(), page=LedgerPage(next_cursor=None, has_more=False)
    )
