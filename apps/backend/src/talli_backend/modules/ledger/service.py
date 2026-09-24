"""Narrow-ledger business invariants and intent-specific posting policy."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from talli_backend.modules.ledger.public import (
    AdministrativeCostCategory,
    AdministrativeCostCorrectionScope,
    ApprovedLossCoverageCapitalReductionFacts,
    ApprovedOneSidedIntercompanyLoanFundingFacts,
    ApprovedOwnerLoanFundingFacts,
    BankInterestIncomeFacts,
    BankLoanEvent,
    BankSuggestionRule,
    CapitalIncreasePhase,
    CapitalReductionRecognition,
    CashCapitalIncreaseFacts,
    CloseCompanyYearCommand,
    CompanyTaxAccrualFacts,
    CompanyYearCloseAssessment,
    CompanyYearCloseEvidence,
    CompanyYearCloseEvidenceKind,
    CompanyYearCloseGapCode,
    CompanyYearCloseOutputKind,
    CompanyYearCloseState,
    CompiledOpeningPositionComponent,
    CorrectedLedgerEntries,
    CorrectHoldingActionCommand,
    GroupContributionFacts,
    GroupContributionPerspective,
    GroupContributionRelationship,
    IntercompanyLoanPerspective,
    IntercompanyLoanRelationship,
    InvestmentClassification,
    InvestmentDividendFacts,
    InvestmentDividendPhase,
    InvestmentCashSettlementFacts,
    InvestmentFundDistributionRecognitionFacts,
    InvestmentPurchaseRecognitionFacts,
    InvestmentSaleRecognitionFacts,
    InvestmentYearEndMeasurementFacts,
    InvestmentSettlementKind,
    LedgerCursor,
    LedgerEntryKind,
    LedgerEntryAmendment,
    LedgerEntryPage,
    LedgerError,
    LedgerLine,
    LedgerPersistence,
    LedgerRiskCode,
    LedgerRiskFlag,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    LockPeriodCommand,
    OpeningBalanceCategory,
    OpeningBalanceComponent,
    OpeningBankInput,
    OpeningBankLoanComponent,
    OpeningCapitalIncreaseComponent,
    OpeningCapitalReductionComponent,
    OpeningDividendPayableComponent,
    OpeningDividendReceivableComponent,
    OpeningInvestmentComponent,
    OpeningPositionMode,
    OrdinaryBankLoanFacts,
    PeriodLock,
    PeriodLockPage,
    PostAdministrativeCostCommand,
    PostBankSuggestionOutcomeCommand,
    PostedLedgerEntry,
    PostReceivedDividendCommand,
    PostReceivedFundDistributionCommand,
    PostInvestmentPurchaseCommand,
    PostInvestmentSaleCommand,
    PostManualJournalCommand,
    PostOwnerDividendDeclaredCommand,
    PostOwnerDividendPaymentCommand,
    PostShareholderLoanCommand,
    PostTaxSettlementCommand,
    RebuildCompanyYearOpeningCommand,
    RecognizeHoldingActionCommand,
    ReverseSupportedHoldingActionCommand,
    ReversedLedgerEntry,
    ReconstructionAssessment,
    ReconstructionAssessmentId,
    ReconstructionEconomicFactCandidates,
    ReconstructionEconomicFactSnapshot,
    ReconstructionEvidenceIssuer,
    ReconstructionEvidenceKind,
    ReconstructionEvidenceStatus,
    ReconstructionGapCode,
    ReconstructionState,
    RecordReconstructionAssessmentCommand,
    RecordOpeningBankInputCommand,
    ShareholderLoanDirection,
    TaxSettlementKind,
)
from talli_backend.shared.kernel import (
    ActorId,
    CompanyId,
    CorrelationId,
    IncomeYear,
    LocalDate,
    Money,
)

_ZERO = Money.nok("0.00")
_SENSITIVE_MANUAL_ACCOUNTS = frozenset(
    {
        "1370",
        "1570",
        "1800",
        "2000",
        "2050",
        "2255",
        "2800",
        "2990",
        "8070",
        "8071",
        "8090",
        "8171",
    }
)
_ADMINISTRATIVE_COST_ACCOUNTS = {
    AdministrativeCostCategory.BANK_FEE: "7770",
    AdministrativeCostCategory.ACCOUNTING_FEE: "6705",
    AdministrativeCostCategory.SOFTWARE: "6420",
    AdministrativeCostCategory.PUBLIC_FEE: "7790",
    AdministrativeCostCategory.LEGAL_ADVISORY: "6720",
    AdministrativeCostCategory.OTHER_ADMIN_COST: "7795",
}

_INVESTMENT_ACCOUNTS = {
    InvestmentClassification.SUBSIDIARY: "1300",
    InvestmentClassification.ASSOCIATE: "1310",
    InvestmentClassification.OTHER_LONG_TERM: "1350",
    InvestmentClassification.CURRENT_LISTED_SHARE: "1810",
    InvestmentClassification.CURRENT_FUND: "1815",
}

_OPENING_BALANCE_RULES = {
    OpeningBalanceCategory.SUBSIDIARY_LOAN_RECEIVABLE: (
        "1320", "Loan receivable from subsidiary", True,
        LedgerSourceCapability.CORPORATE_GOVERNANCE,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.GROUP_COMPANY_LOAN_RECEIVABLE: (
        "1325", "Loan receivable from group company", True,
        LedgerSourceCapability.CORPORATE_GOVERNANCE,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.CORPORATE_SHAREHOLDER_LOAN_RECEIVABLE: (
        "1370", "Loan receivable from corporate shareholder", True,
        LedgerSourceCapability.CORPORATE_GOVERNANCE,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.BANK: (
        "1920", "Bank balance", True, LedgerSourceCapability.BANKING,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.RESTRICTED_BANK: (
        "1921", "Restricted bank balance", True, LedgerSourceCapability.BANKING,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.SUBSIDIARY_INVESTMENT: (
        "1300", "Investment in subsidiary", True, LedgerSourceCapability.INVESTMENTS,
        frozenset({LedgerSourceCapability.DOCUMENTS}),
    ),
    OpeningBalanceCategory.ASSOCIATE_INVESTMENT: (
        "1310", "Investment in associate", True, LedgerSourceCapability.INVESTMENTS,
        frozenset({LedgerSourceCapability.DOCUMENTS}),
    ),
    OpeningBalanceCategory.OTHER_LONG_TERM_INVESTMENT: (
        "1350", "Other long-term investment", True, LedgerSourceCapability.INVESTMENTS,
        frozenset({LedgerSourceCapability.DOCUMENTS}),
    ),
    OpeningBalanceCategory.CURRENT_LISTED_SHARE_INVESTMENT: (
        "1810", "Current listed-share investment", True, LedgerSourceCapability.INVESTMENTS,
        frozenset({LedgerSourceCapability.DOCUMENTS}),
    ),
    OpeningBalanceCategory.CURRENT_FUND_INVESTMENT: (
        "1815", "Current fund investment", True, LedgerSourceCapability.INVESTMENTS,
        frozenset({LedgerSourceCapability.DOCUMENTS}),
    ),
    OpeningBalanceCategory.SUBSCRIPTION_RECEIVABLE: (
        "1500", "Subscription receivable", True,
        LedgerSourceCapability.CORPORATE_GOVERNANCE,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.DIVIDEND_RECEIVABLE: (
        "1530", "Dividend receivable", True, LedgerSourceCapability.INVESTMENTS,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.GROUP_CONTRIBUTION_RECEIVABLE: (
        "1560", "Group contribution receivable", True,
        LedgerSourceCapability.CORPORATE_GOVERNANCE,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.TAX_RECEIVABLE: (
        "1570", "Tax receivable", True,
        LedgerSourceCapability.COMPANY_TAX_FILING,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.ACCRUED_INTEREST_RECEIVABLE: (
        "1700", "Accrued interest receivable", True,
        LedgerSourceCapability.BANKING,
        frozenset({LedgerSourceCapability.DOCUMENTS}),
    ),
    OpeningBalanceCategory.DEFERRED_TAX_ASSET: (
        "1070", "Deferred tax asset", True,
        LedgerSourceCapability.COMPANY_TAX_FILING,
        frozenset({LedgerSourceCapability.DOCUMENTS}),
    ),
    OpeningBalanceCategory.REGISTERED_SHARE_CAPITAL: (
        "2000", "Registered share capital", False,
        LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.SHARE_PREMIUM: (
        "2020", "Share premium", False,
        LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.UNREGISTERED_CAPITAL_INCREASE: (
        "2030", "Unregistered capital increase", False,
        LedgerSourceCapability.CORPORATE_GOVERNANCE,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.UNREGISTERED_CAPITAL_REDUCTION: (
        "2033", "Unregistered capital reduction", True,
        LedgerSourceCapability.CORPORATE_GOVERNANCE,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.OTHER_PAID_IN_EQUITY: (
        "2035", "Other paid-in equity", False,
        LedgerSourceCapability.CORPORATE_GOVERNANCE,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.RETAINED_EARNINGS: (
        "2050", "Retained earnings", False,
        LedgerSourceCapability.ANNUAL_ACCOUNTS_FILING,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.UNCOVERED_LOSS: (
        "2080", "Uncovered loss", True,
        LedgerSourceCapability.ANNUAL_ACCOUNTS_FILING,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.OTHER_EQUITY: (
        "2050", "Other equity", False,
        LedgerSourceCapability.ANNUAL_ACCOUNTS_FILING,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.LONG_TERM_BANK_LOAN_PAYABLE: (
        "2220", "Long-term bank loan payable", False, LedgerSourceCapability.BANKING,
        frozenset({LedgerSourceCapability.DOCUMENTS}),
    ),
    OpeningBalanceCategory.SHORT_TERM_BANK_LOAN_PAYABLE: (
        "2380", "Short-term bank debt", False, LedgerSourceCapability.BANKING,
        frozenset({LedgerSourceCapability.DOCUMENTS}),
    ),
    OpeningBalanceCategory.OWNER_LOAN_PAYABLE: (
        "2255", "Owner loan payable", False,
        LedgerSourceCapability.CORPORATE_GOVERNANCE,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.INTERCOMPANY_LOAN_PAYABLE: (
        "2260", "Intercompany loan payable", False,
        LedgerSourceCapability.CORPORATE_GOVERNANCE,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.SUPPLIER_PAYABLE: (
        "2400", "Supplier payable", False, LedgerSourceCapability.DOCUMENTS,
        LedgerSourceCapability.ANNUAL_ACCOUNTS_FILING,
    ),
    OpeningBalanceCategory.CURRENT_TAX_PAYABLE: (
        "2500", "Current tax payable", False,
        LedgerSourceCapability.COMPANY_TAX_FILING,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.DEFERRED_TAX_LIABILITY: (
        "2120", "Deferred tax liability", False,
        LedgerSourceCapability.COMPANY_TAX_FILING,
        frozenset({LedgerSourceCapability.DOCUMENTS}),
    ),
    OpeningBalanceCategory.ACCRUED_INTEREST_PAYABLE: (
        "2965", "Accrued interest payable", False,
        LedgerSourceCapability.BANKING,
        frozenset({LedgerSourceCapability.DOCUMENTS}),
    ),
    OpeningBalanceCategory.DIVIDEND_PAYABLE: (
        "2800", "Dividend payable", False,
        LedgerSourceCapability.CORPORATE_GOVERNANCE,
        LedgerSourceCapability.DOCUMENTS,
    ),
    OpeningBalanceCategory.GROUP_CONTRIBUTION_PAYABLE: (
        "2960", "Group contribution payable", False,
        LedgerSourceCapability.CORPORATE_GOVERNANCE,
        LedgerSourceCapability.DOCUMENTS,
    ),
}


def _opening_sources_are_valid(
    *,
    primary_source: object,
    corroborating_sources: tuple[object, ...],
    expected_primary: LedgerSourceCapability,
    expected_corroborating: frozenset[LedgerSourceCapability],
) -> bool:
    return (
        getattr(primary_source, "capability", None) is expected_primary
        and frozenset(
            getattr(source, "capability", None) for source in corroborating_sources
        )
        == expected_corroborating
        and len(corroborating_sources) == len(expected_corroborating)
    )


def _opening_rule_component(
    component: object,
    *,
    mode: OpeningPositionMode,
    component_kind: str,
    category: OpeningBalanceCategory,
    reference_id: str,
    lifecycle_phase: str | None = None,
) -> CompiledOpeningPositionComponent:
    account, description, is_debit, primary, corroborating = (
        _OPENING_BALANCE_RULES[category]
    )
    if mode is OpeningPositionMode.NEW_COMPANY:
        new_company_sources = {
            OpeningBalanceCategory.BANK: (
                LedgerSourceCapability.LEDGER,
                frozenset({LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING}),
            ),
            OpeningBalanceCategory.REGISTERED_SHARE_CAPITAL: (
                LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING,
                frozenset({LedgerSourceCapability.LEDGER}),
            ),
            OpeningBalanceCategory.RETAINED_EARNINGS: (
                LedgerSourceCapability.LEDGER,
                frozenset({LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING}),
            ),
            OpeningBalanceCategory.UNCOVERED_LOSS: (
                LedgerSourceCapability.LEDGER,
                frozenset({LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING}),
            ),
        }
        try:
            primary, expected_corroborating = new_company_sources[category]
        except KeyError:
            raise LedgerError.invalid_input(
                "LEDGER_OPENING_BALANCE_INVALID"
            ) from None
    else:
        expected_corroborating = (
            corroborating
            if isinstance(corroborating, frozenset)
            else frozenset({corroborating})
        )
    primary_source = component.primary_source
    corroborating_sources = component.corroborating_sources
    if not _opening_sources_are_valid(
        primary_source=primary_source,
        corroborating_sources=corroborating_sources,
        expected_primary=primary,
        expected_corroborating=expected_corroborating,
    ):
        raise LedgerError.precondition_failed("LEDGER_OPENING_EVIDENCE_INVALID")
    return CompiledOpeningPositionComponent(
        component_kind=component_kind,
        category=category,
        reference_id=reference_id,
        lifecycle_phase=lifecycle_phase,
        amount=component.amount,
        nominal_increase=None,
        share_premium=None,
        nominal_reduction=None,
        account=account,
        description=description,
        is_debit=is_debit,
        primary_source=primary_source,
        corroborating_sources=corroborating_sources,
    )


def _opening_expansion(
    component: object,
    *,
    mode: OpeningPositionMode,
) -> tuple[CompiledOpeningPositionComponent, ...]:
    if isinstance(component, OpeningBalanceComponent):
        return (
            _opening_rule_component(
                component,
                mode=mode,
                component_kind="CLASSIFIED_BALANCE",
                category=component.category,
                reference_id=str(component.reference_id),
            ),
        )
    if isinstance(component, OpeningBankLoanComponent):
        if mode is OpeningPositionMode.NEW_COMPANY:
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        return (
            _opening_rule_component(
                component,
                mode=mode,
                component_kind="BANK_LOAN",
                category=component.category,
                reference_id=str(component.loan_reference_id),
                lifecycle_phase=component.maturity.value,
            ),
        )
    if isinstance(component, OpeningInvestmentComponent):
        if mode is OpeningPositionMode.NEW_COMPANY:
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        return (
            _opening_rule_component(
                component,
                mode=mode,
                component_kind="INVESTMENT",
                category=component.category,
                reference_id=str(component.investment_reference_id),
                lifecycle_phase=component.classification.value,
            ),
        )
    if isinstance(component, OpeningDividendReceivableComponent):
        if mode is OpeningPositionMode.NEW_COMPANY:
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        return (
            _opening_rule_component(
                component,
                mode=mode,
                component_kind="DIVIDEND_RECEIVABLE",
                category=component.category,
                reference_id=str(component.decision_reference_id),
                lifecycle_phase="FINAL_DECISION_UNSETTLED",
            ),
        )
    if isinstance(component, OpeningDividendPayableComponent):
        if mode is OpeningPositionMode.NEW_COMPANY:
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        return (
            _opening_rule_component(
                component,
                mode=mode,
                component_kind="DIVIDEND_PAYABLE",
                category=component.category,
                reference_id=str(component.decision_reference_id),
                lifecycle_phase="DECLARED_UNPAID",
            ),
        )
    if isinstance(component, OpeningCapitalIncreaseComponent):
        if mode is OpeningPositionMode.NEW_COMPANY:
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        expected_corroborating = (
            frozenset({LedgerSourceCapability.DOCUMENTS})
            if component.phase is CapitalIncreasePhase.BINDING_SUBSCRIPTION
            else frozenset(
                {LedgerSourceCapability.BANKING, LedgerSourceCapability.DOCUMENTS}
            )
        )
        if not _opening_sources_are_valid(
            primary_source=component.primary_source,
            corroborating_sources=component.corroborating_sources,
            expected_primary=LedgerSourceCapability.CORPORATE_GOVERNANCE,
            expected_corroborating=expected_corroborating,
        ):
            raise LedgerError.precondition_failed("LEDGER_OPENING_EVIDENCE_INVALID")
        amount = Money.nok(
            component.nominal_increase.amount + component.share_premium.amount
        )
        debit_category = (
            OpeningBalanceCategory.SUBSCRIPTION_RECEIVABLE
            if component.phase is CapitalIncreasePhase.BINDING_SUBSCRIPTION
            else OpeningBalanceCategory.RESTRICTED_BANK
        )
        debit_account, debit_description, _, _, _ = _OPENING_BALANCE_RULES[
            debit_category
        ]
        credit_account, credit_description, _, _, _ = _OPENING_BALANCE_RULES[
            OpeningBalanceCategory.UNREGISTERED_CAPITAL_INCREASE
        ]
        common = {
            "component_kind": "CAPITAL_INCREASE",
            "reference_id": str(component.capital_increase_reference_id),
            "lifecycle_phase": component.phase.value,
            "amount": amount,
            "nominal_increase": component.nominal_increase,
            "share_premium": component.share_premium,
            "nominal_reduction": None,
            "primary_source": component.primary_source,
            "corroborating_sources": component.corroborating_sources,
        }
        return (
            CompiledOpeningPositionComponent(
                category=debit_category,
                account=debit_account,
                description=debit_description,
                is_debit=True,
                **common,
            ),
            CompiledOpeningPositionComponent(
                category=OpeningBalanceCategory.UNREGISTERED_CAPITAL_INCREASE,
                account=credit_account,
                description=credit_description,
                is_debit=False,
                **common,
            ),
        )
    if isinstance(component, OpeningCapitalReductionComponent):
        if mode is OpeningPositionMode.NEW_COMPANY:
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        if not _opening_sources_are_valid(
            primary_source=component.primary_source,
            corroborating_sources=component.corroborating_sources,
            expected_primary=LedgerSourceCapability.CORPORATE_GOVERNANCE,
            expected_corroborating=frozenset({LedgerSourceCapability.DOCUMENTS}),
        ):
            raise LedgerError.precondition_failed("LEDGER_OPENING_EVIDENCE_INVALID")
        common = {
            "component_kind": "CAPITAL_REDUCTION",
            "reference_id": str(component.capital_reduction_reference_id),
            "lifecycle_phase": component.recognition.value,
            "amount": component.nominal_reduction,
            "nominal_increase": None,
            "share_premium": None,
            "nominal_reduction": component.nominal_reduction,
            "primary_source": component.primary_source,
            "corroborating_sources": component.corroborating_sources,
        }
        return (
            CompiledOpeningPositionComponent(
                category=OpeningBalanceCategory.UNREGISTERED_CAPITAL_REDUCTION,
                account="2033",
                description="Unregistered capital reduction",
                is_debit=True,
                **common,
            ),
            CompiledOpeningPositionComponent(
                category=OpeningBalanceCategory.UNCOVERED_LOSS,
                account="2080",
                description="Loss covered by unregistered capital reduction",
                is_debit=False,
                **common,
            ),
        )
    raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")


def _owner_loan_funding_lines(
    amount: Money,
    *,
    counterparty_name: str | None = None,
) -> tuple[LedgerLine, LedgerLine]:
    received_description = (
        "Owner-loan funding received"
        if counterparty_name is None
        else f"Loan received from {counterparty_name}"
    )
    payable_description = (
        "Debt to owner"
        if counterparty_name is None
        else f"Loan payable to {counterparty_name}"
    )
    return (
        LedgerLine("1920", received_description, amount, _ZERO),
        LedgerLine("2255", payable_description, _ZERO, amount),
    )


def _administrative_cost_lines(
    category: AdministrativeCostCategory,
    amount: Money,
    *,
    description: str,
) -> tuple[LedgerLine, LedgerLine]:
    return (
        LedgerLine(_ADMINISTRATIVE_COST_ACCOUNTS[category], description, amount, _ZERO),
        LedgerLine("1920", "Paid from bank", _ZERO, amount),
    )


_BANK_SUGGESTION_LINES = {
    BankSuggestionRule.BANK_FEE: ("7770", "Bankomkostninger", False),
    BankSuggestionRule.SYSTEM_SUBSCRIPTION: ("6700", "Fremmede tjenester", False),
    BankSuggestionRule.DEPOSIT_INTEREST: ("8050", "Annen renteinntekt", True),
}
_RECONSTRUCTION_EVIDENCE_REQUIREMENTS = (
    (ReconstructionEvidenceKind.PRIOR_CLOSING_OPENING, ReconstructionEvidenceIssuer.LEDGER),
    (ReconstructionEvidenceKind.BANK_MOVEMENTS, ReconstructionEvidenceIssuer.BANKING),
    (ReconstructionEvidenceKind.BANK_RECONCILIATION, ReconstructionEvidenceIssuer.BANKING),
    (ReconstructionEvidenceKind.INVESTMENTS, ReconstructionEvidenceIssuer.INVESTMENTS),
    (
        ReconstructionEvidenceKind.SHAREHOLDERS,
        ReconstructionEvidenceIssuer.SHAREHOLDER_REGISTER_FILING,
    ),
    (
        ReconstructionEvidenceKind.LOANS,
        ReconstructionEvidenceIssuer.BANKING,
    ),
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
_FULL_YEAR_COVERAGE_EVIDENCE = frozenset(ReconstructionEvidenceKind)
_COMPANY_YEAR_CLOSE_REQUIREMENTS = (
    (
        CompanyYearCloseEvidenceKind.BANK_ROWS_RESOLVED,
        LedgerSourceCapability.BANKING,
        CompanyYearCloseGapCode.UNRESOLVED_BANK_ROW,
    ),
    (
        CompanyYearCloseEvidenceKind.MATERIAL_BALANCES_DOCUMENTED,
        LedgerSourceCapability.DOCUMENTS,
        CompanyYearCloseGapCode.MATERIAL_BALANCE_UNDOCUMENTED,
    ),
    (
        CompanyYearCloseEvidenceKind.REPORTING_RECONCILED,
        LedgerSourceCapability.LEDGER,
        CompanyYearCloseGapCode.REPORTING_NOT_RECONCILED,
    ),
)
_RECONSTRUCTION_GAP_BY_KIND = {
    ReconstructionEvidenceKind.PRIOR_CLOSING_OPENING: ReconstructionGapCode.PRIOR_CLOSING_MISMATCH,
    ReconstructionEvidenceKind.BANK_MOVEMENTS: ReconstructionGapCode.BANK_MOVEMENTS_INCOMPLETE,
    ReconstructionEvidenceKind.BANK_RECONCILIATION: ReconstructionGapCode.BANK_NOT_RECONCILED,
    ReconstructionEvidenceKind.INVESTMENTS: ReconstructionGapCode.INVESTMENTS_UNCONFIRMED,
    ReconstructionEvidenceKind.SHAREHOLDERS: ReconstructionGapCode.SHAREHOLDERS_UNCONFIRMED,
    ReconstructionEvidenceKind.LOANS: ReconstructionGapCode.LOANS_UNCONFIRMED,
    ReconstructionEvidenceKind.EQUITY: ReconstructionGapCode.EQUITY_UNCONFIRMED,
    ReconstructionEvidenceKind.TAX_HISTORY: ReconstructionGapCode.TAX_HISTORY_UNCONFIRMED,
    ReconstructionEvidenceKind.CURRENT_YEAR_ACTIVITY: ReconstructionGapCode.CURRENT_ACTIVITY_INCOMPLETE,
    ReconstructionEvidenceKind.DOCUMENTS: ReconstructionGapCode.DOCUMENTS_INCOMPLETE,
    ReconstructionEvidenceKind.UNSUPPORTED_ACTIVITY_CHECK: ReconstructionGapCode.UNSUPPORTED_ACTIVITY_FOUND,
}


def _positive(value: Money, code: str) -> None:
    if value.amount <= 0:
        raise LedgerError.invalid_input(code)


def _balanced(lines: tuple[LedgerLine, ...], *, permit_zero_line: bool = False) -> None:
    if len(lines) < 2:
        raise LedgerError.invalid_input("LEDGER_ENTRY_REQUIRES_TWO_LINES")
    if not permit_zero_line and any(
        line.debit.amount == 0 and line.credit.amount == 0 for line in lines
    ):
        raise LedgerError.invalid_input("LEDGER_LINE_ZERO")
    currencies = {line.debit.currency for line in lines} | {
        line.credit.currency for line in lines
    }
    if len(currencies) != 1:
        raise LedgerError.invalid_input("LEDGER_CURRENCY_MISMATCH")
    debit = sum((line.debit.amount for line in lines), start=Decimal("0.00"))
    credit = sum((line.credit.amount for line in lines), start=Decimal("0.00"))
    if debit != credit:
        raise LedgerError.invalid_input("LEDGER_ENTRY_UNBALANCED")


class LedgerService:
    def __init__(self, persistence: LedgerPersistence) -> None:
        self._persistence = persistence

    async def record_opening_bank_input(
        self, command: RecordOpeningBankInputCommand
    ) -> OpeningBankInput:
        recorded = await self._persistence.record_opening_bank_input(command)
        if (
            not isinstance(recorded, OpeningBankInput)
            or recorded.snapshot_id != command.snapshot_id
            or recorded.company_id != command.company_id
            or recorded.income_year != command.income_year
            or recorded.bank_balance != command.bank_balance
            or recorded.recorded_by != command.actor_id
        ):
            raise LedgerError.unavailable()
        return recorded

    async def read_opening_bank_inputs(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear | None,
        correlation_id: CorrelationId,
    ) -> tuple[OpeningBankInput, ...]:
        rows = await self._persistence.read_opening_bank_inputs(
            actor_id=actor_id, company_id=company_id,
            income_year=income_year, correlation_id=correlation_id,
        )
        if (
            not isinstance(rows, tuple)
            or any(not isinstance(row, OpeningBankInput) for row in rows)
            or len({row.snapshot_id for row in rows}) != len(rows)
            or any(row.company_id != company_id or (
                income_year is not None and row.income_year != income_year
            ) for row in rows)
        ):
            raise LedgerError.unavailable()
        return rows

    async def get_company_year_close_assessment(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        correlation_id: CorrelationId,
    ) -> CompanyYearCloseAssessment:
        return await self._persistence.get_company_year_close_assessment(
            actor_id=actor_id,
            company_id=company_id,
            income_year=income_year,
            correlation_id=correlation_id,
        )

    async def get_reconstruction_economic_fact_candidates(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        as_of: LocalDate,
        correlation_id: CorrelationId,
    ) -> ReconstructionEconomicFactCandidates:
        if as_of.value.year != int(income_year):
            raise LedgerError.invalid_input("LEDGER_RECONSTRUCTION_COVERAGE_INVALID")
        return await self._persistence.get_reconstruction_economic_fact_candidates(
            actor_id=actor_id,
            company_id=company_id,
            income_year=income_year,
            as_of=as_of,
            correlation_id=correlation_id,
        )

    async def get_reconstruction_economic_facts(
        self,
        *,
        actor_id: ActorId,
        assessment_id: ReconstructionAssessmentId,
        correlation_id: CorrelationId,
    ) -> ReconstructionEconomicFactSnapshot:
        return await self._persistence.get_reconstruction_economic_facts(
            actor_id=actor_id,
            assessment_id=assessment_id,
            correlation_id=correlation_id,
        )

    async def close_company_year(
        self, command: CloseCompanyYearCommand
    ) -> CompanyYearCloseAssessment:
        if command.period_end.value.year != int(command.income_year):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        expected = {
            (kind, issuer): gap
            for kind, issuer, gap in _COMPANY_YEAR_CLOSE_REQUIREMENTS
        }
        by_requirement: dict[
            tuple[CompanyYearCloseEvidenceKind, LedgerSourceCapability],
            CompanyYearCloseEvidence,
        ] = {}
        for item in command.evidence:
            key = (item.kind, item.issuer)
            if key not in expected or key in by_requirement:
                raise LedgerError.precondition_failed(
                    "LEDGER_COMPANY_YEAR_CLOSE_EVIDENCE_INVALID"
                )
            by_requirement[key] = item

        canonical_evidence: list[CompanyYearCloseEvidence] = []
        for kind, issuer, expected_gap in _COMPANY_YEAR_CLOSE_REQUIREMENTS:
            item = by_requirement.get((kind, issuer))
            if item is None:
                continue
            if item.confirmation is ReconstructionEvidenceStatus.CONFIRMED:
                expected_outputs = (
                    set(CompanyYearCloseOutputKind)
                    if kind is CompanyYearCloseEvidenceKind.REPORTING_RECONCILED
                    else set()
                )
            else:
                expected_outputs = set()
            output_kinds = [output.kind for output in item.outputs]
            if len(output_kinds) != len(set(output_kinds)) or set(
                output_kinds
            ) != expected_outputs:
                raise LedgerError.precondition_failed(
                    "LEDGER_COMPANY_YEAR_CLOSE_EVIDENCE_INVALID"
                )
            canonical_evidence.append(
                replace(
                    item,
                    outputs=tuple(
                        sorted(item.outputs, key=lambda output: output.kind.value)
                    ),
                )
            )
            if (
                item.confirmation is not ReconstructionEvidenceStatus.CONFIRMED
                and item.gap_code is not expected_gap
            ):
                raise LedgerError.precondition_failed(
                    "LEDGER_COMPANY_YEAR_CLOSE_EVIDENCE_INVALID"
                )

        if len({item.ledger_state_digest for item in canonical_evidence}) > 1:
            raise LedgerError.precondition_failed(
                "LEDGER_COMPANY_YEAR_CLOSE_EVIDENCE_INVALID"
            )

        canonical = tuple(canonical_evidence)
        replay = await self._persistence.get_company_year_close_replay(
            command,
            evidence=canonical,
        )
        if replay is not None:
            return replay

        current = await self._persistence.get_reconstruction_assessment(
            actor_id=command.actor_id,
            company_id=command.company_id,
            income_year=command.income_year,
            correlation_id=command.correlation_id,
        )
        if (
            current.assessment_id != command.reconstruction_assessment_id
            or current.evidence_digest != command.reconstruction_evidence_digest
            or current.as_of != command.period_end
            or current.ledger_state_digest is None
            or current.economic_facts_digest is None
            or current.economic_fact_count is None
            or current.source_evidence_digest is None
            or current.source_evidence_count is None
            or any(
                item.ledger_state_digest != current.ledger_state_digest
                for item in canonical
            )
            or any(
                output.economic_facts_digest != current.economic_facts_digest
                for item in canonical
                for output in item.outputs
            )
        ):
            raise LedgerError.precondition_failed(
                "LEDGER_COMPANY_YEAR_CLOSE_RECONSTRUCTION_STALE"
            )

        gaps: list[CompanyYearCloseGapCode] = []
        if (command.period_end.value.month, command.period_end.value.day) != (12, 31):
            gaps.append(CompanyYearCloseGapCode.PERIOD_END_UNSUPPORTED)
        if current.state is not ReconstructionState.READY:
            gaps.append(CompanyYearCloseGapCode.SOURCE_INCOMPLETE)
            if ReconstructionGapCode.BANK_NOT_RECONCILED in current.gap_codes:
                gaps.append(CompanyYearCloseGapCode.BANK_NOT_RECONCILED)
            if ReconstructionGapCode.UNSUPPORTED_ACTIVITY_FOUND in current.gap_codes:
                gaps.append(CompanyYearCloseGapCode.UNSUPPORTED_TRANSACTION)
        if len(by_requirement) != len(expected):
            gaps.append(CompanyYearCloseGapCode.CHECK_EVIDENCE_INCOMPLETE)

        for item in canonical:
            if item.coverage_through != command.period_end:
                if CompanyYearCloseGapCode.CHECK_EVIDENCE_INCOMPLETE not in gaps:
                    gaps.append(CompanyYearCloseGapCode.CHECK_EVIDENCE_INCOMPLETE)
            if item.confirmation is not ReconstructionEvidenceStatus.CONFIRMED:
                gap = item.gap_code
                if gap is None:
                    raise LedgerError.precondition_failed(
                        "LEDGER_COMPANY_YEAR_CLOSE_EVIDENCE_INVALID"
                    )
                if gap not in gaps:
                    gaps.append(gap)

        gap_codes = tuple(dict.fromkeys(gaps))
        state = (
            CompanyYearCloseState.CLOSED
            if not gap_codes
            else CompanyYearCloseState.BLOCKED
        )
        return await self._persistence.record_company_year_close(
            command,
            evidence=canonical,
            state=state,
            gap_codes=gap_codes,
        )

    async def correct_holding_action(
        self, command: CorrectHoldingActionCommand
    ) -> CorrectedLedgerEntries:
        if command.event_date.value.year != int(command.income_year):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        if command.primary_source.capability is not LedgerSourceCapability.DOCUMENTS or {
            source.capability for source in command.corroborating_sources
        } != {LedgerSourceCapability.BANKING}:
            raise LedgerError.precondition_failed("LEDGER_SOURCE_CAPABILITY_MISMATCH")
        replacement = command.replacement
        _positive(replacement.amount, "LEDGER_ADMINISTRATIVE_COST_NOT_POSITIVE")
        if (
            not replacement.supplier_name.strip()
            or len(replacement.supplier_name) > 255
            or any(
                not value.strip() or len(value) > 500
                for value in (
                    replacement.description,
                    replacement.business_purpose,
                )
            )
        ):
            raise LedgerError.precondition_failed(
                "LEDGER_ADMINISTRATIVE_COST_EVIDENCE_INCOMPLETE"
            )
        if (
            replacement.delivery_date.value.year != int(command.income_year)
            or replacement.document_date.value > command.event_date.value
            or replacement.delivery_date.value > command.event_date.value
            or not replacement.payment_confirmed
        ):
            raise LedgerError.precondition_failed(
                "LEDGER_ADMINISTRATIVE_COST_EVIDENCE_INCOMPLETE"
            )
        if replacement.correction_scope is not (
            AdministrativeCostCorrectionScope.CURRENT_COMPANY_YEAR
        ):
            raise LedgerError.precondition_failed(
                "LEDGER_PRIOR_YEAR_CORRECTION_POLICY_UNRESOLVED"
            )
        if replacement.blocks:
            raise LedgerError.precondition_failed(
                "LEDGER_ADMINISTRATIVE_COST_UNSUPPORTED"
            )
        lines = _administrative_cost_lines(
            replacement.category,
            replacement.amount,
            description=(
                f"Corrected administrative cost: {replacement.supplier_name.strip()}"
            ),
        )
        return await self._persistence.correct_entry(
            command,
            entry_kind=LedgerEntryKind.ADMINISTRATIVE_COST,
            memo=command.reason,
            lines=lines,
        )

    async def reverse_supported_holding_action(
        self, command: ReverseSupportedHoldingActionCommand
    ) -> ReversedLedgerEntry:
        if command.event_date.value.year != int(command.income_year):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        if command.correction_source.capability is not LedgerSourceCapability.DOCUMENTS:
            raise LedgerError.precondition_failed("LEDGER_SOURCE_CAPABILITY_MISMATCH")
        return await self._persistence.reverse_supported_entry(command)

    async def recognize_holding_action(
        self, command: RecognizeHoldingActionCommand
    ) -> PostedLedgerEntry:
        if command.event_date.value.year != int(command.income_year):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        sources = (command.primary_source, *command.corroborating_sources)
        source_keys = {
            (source.capability, source.record_id.value, source.revision)
            for source in sources
        }
        if len(source_keys) != len(sources):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")

        facts = command.facts
        required_sources: frozenset[LedgerSourceCapability]
        primary_source_capability: LedgerSourceCapability
        entry_kind: LedgerEntryKind
        memo: str
        lines: tuple[LedgerLine, ...]
        if isinstance(facts, BankInterestIncomeFacts):
            required_sources = frozenset({LedgerSourceCapability.BANKING})
            primary_source_capability = LedgerSourceCapability.BANKING
            _positive(facts.amount, "LEDGER_INVALID_INPUT")
            entry_kind = LedgerEntryKind.BANK_INTEREST
            memo = "Bank interest supported by bank advice"
            lines = (
                LedgerLine("1920", "Bank interest received", facts.amount, _ZERO),
                LedgerLine("8050", "Bank interest income", _ZERO, facts.amount),
            )
        elif isinstance(facts, InvestmentDividendFacts):
            _positive(facts.gross_amount, "LEDGER_INVALID_INPUT")
            entry_kind = LedgerEntryKind.DIVIDEND_RECEIVED
            primary_source_capability = LedgerSourceCapability.INVESTMENTS
            if facts.phase is InvestmentDividendPhase.FINAL_DECISION:
                if (
                    facts.decision_entry_id is not None
                    or facts.decision_reference_id is not None
                ):
                    raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
                required_sources = frozenset(
                    {
                        LedgerSourceCapability.INVESTMENTS,
                        LedgerSourceCapability.DOCUMENTS,
                    }
                )
                memo = "Final investment-dividend decision recognized"
                lines = (
                    LedgerLine(
                        "1530", "Dividend receivable", facts.gross_amount, _ZERO
                    ),
                    LedgerLine(
                        "8070", "Dividend income", _ZERO, facts.gross_amount
                    ),
                )
            elif facts.phase is InvestmentDividendPhase.PAYMENT:
                if (facts.decision_entry_id is None) == (
                    facts.decision_reference_id is None
                ):
                    raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
                required_sources = frozenset(
                    {
                        LedgerSourceCapability.INVESTMENTS,
                        LedgerSourceCapability.BANKING,
                    }
                )
                memo = "Investment-dividend receivable settled"
                lines = (
                    LedgerLine("1920", "Dividend received", facts.gross_amount, _ZERO),
                    LedgerLine(
                        "1530", "Dividend receivable settled", _ZERO, facts.gross_amount
                    ),
                )
            else:
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        elif isinstance(facts, InvestmentPurchaseRecognitionFacts):
            required_sources = frozenset(
                {
                    LedgerSourceCapability.INVESTMENTS,
                    LedgerSourceCapability.DOCUMENTS,
                }
            )
            primary_source_capability = LedgerSourceCapability.INVESTMENTS
            _positive(facts.acquisition_cost, "LEDGER_INVALID_INPUT")
            investment_name = facts.investment_name.strip()
            account = _INVESTMENT_ACCOUNTS.get(facts.classification)
            if not investment_name or len(investment_name) > 255 or account is None:
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
            entry_kind = LedgerEntryKind.SHARE_PURCHASE
            memo = f"Investment recognized: {investment_name}"
            lines = (
                LedgerLine(
                    account,
                    f"Investment in {investment_name}",
                    facts.acquisition_cost,
                    _ZERO,
                ),
                LedgerLine(
                    "2990",
                    "Investment settlement payable",
                    _ZERO,
                    facts.acquisition_cost,
                ),
            )
        elif isinstance(facts, InvestmentSaleRecognitionFacts):
            required_sources = frozenset(
                {
                    LedgerSourceCapability.INVESTMENTS,
                    LedgerSourceCapability.DOCUMENTS,
                }
            )
            primary_source_capability = LedgerSourceCapability.INVESTMENTS
            _positive(facts.net_proceeds, "LEDGER_INVALID_INPUT")
            if facts.carrying_amount.amount < 0:
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
            if facts.net_proceeds.currency != facts.carrying_amount.currency:
                raise LedgerError.invalid_input("LEDGER_CURRENCY_MISMATCH")
            investment_name = facts.investment_name.strip()
            account = _INVESTMENT_ACCOUNTS.get(facts.classification)
            if not investment_name or len(investment_name) > 255 or account is None:
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
            entry_kind = LedgerEntryKind.SHARE_SALE
            memo = f"Investment sale recognized: {investment_name}"
            lines = (
                LedgerLine(
                    "1570",
                    "Investment settlement receivable",
                    facts.net_proceeds,
                    _ZERO,
                ),
                LedgerLine(
                    account,
                    f"Cost basis reduction: {investment_name}",
                    _ZERO,
                    facts.carrying_amount,
                ),
            )
            gain_or_loss = facts.net_proceeds.amount - facts.carrying_amount.amount
            if gain_or_loss > 0:
                lines += (
                    LedgerLine(
                        "8071",
                        f"Share sale gain: {investment_name}",
                        _ZERO,
                        Money.nok(gain_or_loss),
                    ),
                )
            elif gain_or_loss < 0:
                lines += (
                    LedgerLine(
                        "8171",
                        f"Share sale loss: {investment_name}",
                        Money.nok(abs(gain_or_loss)),
                        _ZERO,
                    ),
                )
        elif isinstance(facts, InvestmentFundDistributionRecognitionFacts):
            required_sources = frozenset(
                {
                    LedgerSourceCapability.INVESTMENTS,
                    LedgerSourceCapability.DOCUMENTS,
                }
            )
            primary_source_capability = LedgerSourceCapability.INVESTMENTS
            _positive(facts.gross_amount, "LEDGER_INVALID_INPUT")
            fund_name = facts.fund_name.strip()
            if (
                not fund_name
                or len(fund_name) > 255
                or facts.dividend_portion.amount < 0
                or facts.interest_portion.amount < 0
                or len(
                    {
                        facts.gross_amount.currency,
                        facts.dividend_portion.currency,
                        facts.interest_portion.currency,
                    }
                )
                != 1
                or facts.dividend_portion.amount + facts.interest_portion.amount
                != facts.gross_amount.amount
            ):
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
            entry_kind = LedgerEntryKind.DIVIDEND_RECEIVED
            memo = f"Fund distribution recognized: {fund_name}"
            lines = (
                LedgerLine(
                    "1530",
                    "Fund distribution receivable",
                    facts.gross_amount,
                    _ZERO,
                ),
            )
            if facts.dividend_portion.amount > 0:
                lines += (
                    LedgerLine(
                        "8070",
                        f"Fund dividend from {fund_name}",
                        _ZERO,
                        facts.dividend_portion,
                    ),
                )
            if facts.interest_portion.amount > 0:
                lines += (
                    LedgerLine(
                        "8050",
                        f"Fund interest income from {fund_name}",
                        _ZERO,
                        facts.interest_portion,
                    ),
                )
        elif isinstance(facts, InvestmentCashSettlementFacts):
            required_sources = frozenset(
                {
                    LedgerSourceCapability.INVESTMENTS,
                    LedgerSourceCapability.BANKING,
                }
            )
            primary_source_capability = LedgerSourceCapability.INVESTMENTS
            _positive(facts.amount, "LEDGER_INVALID_INPUT")
            if facts.kind is InvestmentSettlementKind.PURCHASE_PAYABLE:
                entry_kind = LedgerEntryKind.SHARE_PURCHASE
                memo = "Investment purchase payable settled"
                lines = (
                    LedgerLine(
                        "2990", "Investment settlement payable cleared", facts.amount, _ZERO
                    ),
                    LedgerLine("1920", "Investment paid from bank", _ZERO, facts.amount),
                )
            elif facts.kind is InvestmentSettlementKind.SALE_RECEIVABLE:
                entry_kind = LedgerEntryKind.SHARE_SALE
                memo = "Investment sale receivable settled"
                lines = (
                    LedgerLine("1920", "Investment proceeds received", facts.amount, _ZERO),
                    LedgerLine(
                        "1570", "Investment settlement receivable cleared", _ZERO, facts.amount
                    ),
                )
            elif facts.kind in {
                InvestmentSettlementKind.DIVIDEND_RECEIVABLE,
                InvestmentSettlementKind.FUND_DISTRIBUTION_RECEIVABLE,
            }:
                entry_kind = LedgerEntryKind.DIVIDEND_RECEIVED
                memo = "Investment income receivable settled"
                lines = (
                    LedgerLine("1920", "Investment income received", facts.amount, _ZERO),
                    LedgerLine(
                        "1530", "Investment income receivable cleared", _ZERO, facts.amount
                    ),
                )
            else:
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        elif isinstance(facts, InvestmentYearEndMeasurementFacts):
            required_sources = frozenset(
                {
                    LedgerSourceCapability.INVESTMENTS,
                    LedgerSourceCapability.DOCUMENTS,
                }
            )
            primary_source_capability = LedgerSourceCapability.INVESTMENTS
            investment_name = facts.investment_name.strip()
            account = _INVESTMENT_ACCOUNTS.get(facts.classification)
            if (
                not investment_name
                or len(investment_name) > 255
                or account is None
                or facts.pre_measurement_book_value.amount < 0
                or facts.closing_book_value.amount < 0
                or facts.pre_measurement_book_value.currency
                != facts.closing_book_value.currency
                or facts.closing_book_value.amount
                == facts.pre_measurement_book_value.amount
            ):
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
            is_impairment = (
                facts.closing_book_value.amount
                < facts.pre_measurement_book_value.amount
            )
            amount = Money.nok(abs(
                facts.pre_measurement_book_value.amount
                - facts.closing_book_value.amount
            ))
            entry_kind = LedgerEntryKind.INVESTMENT_MEASUREMENT
            if is_impairment:
                memo = f"Year-end investment impairment: {investment_name}"
                lines = (
                    LedgerLine(
                        "8172",
                        f"Investment impairment: {investment_name}",
                        amount,
                        _ZERO,
                    ),
                    LedgerLine(
                        account,
                        f"Investment carrying value reduced: {investment_name}",
                        _ZERO,
                        amount,
                    ),
                )
            else:
                memo = f"Year-end investment impairment reversal: {investment_name}"
                lines = (
                    LedgerLine(
                        account,
                        f"Investment carrying value restored: {investment_name}",
                        amount,
                        _ZERO,
                    ),
                    LedgerLine(
                        "8172",
                        f"Investment impairment reversed: {investment_name}",
                        _ZERO,
                        amount,
                    ),
                )
        elif isinstance(facts, ApprovedOwnerLoanFundingFacts):
            required_sources = frozenset(
                {
                    LedgerSourceCapability.CORPORATE_GOVERNANCE,
                    LedgerSourceCapability.BANKING,
                }
            )
            primary_source_capability = LedgerSourceCapability.CORPORATE_GOVERNANCE
            _positive(facts.principal, "LEDGER_INVALID_INPUT")
            entry_kind = LedgerEntryKind.SHAREHOLDER_LOAN
            memo = "Approved owner-to-company loan funding"
            lines = _owner_loan_funding_lines(facts.principal)
        elif isinstance(facts, ApprovedOneSidedIntercompanyLoanFundingFacts):
            required_sources = frozenset(
                {
                    LedgerSourceCapability.CORPORATE_GOVERNANCE,
                    LedgerSourceCapability.BANKING,
                }
            )
            primary_source_capability = LedgerSourceCapability.CORPORATE_GOVERNANCE
            _positive(facts.principal, "LEDGER_INVALID_INPUT")
            entry_kind = LedgerEntryKind.INTERCOMPANY_LOAN
            memo = f"Approved intercompany loan funding: {facts.perspective.value}"
            if facts.perspective is IntercompanyLoanPerspective.LENDER:
                receivable_account = (
                    "1320"
                    if facts.relationship
                    is IntercompanyLoanRelationship.PARENT_TO_SUBSIDIARY
                    else "1325"
                )
                lines = (
                    LedgerLine(
                        receivable_account,
                        "Intercompany loan receivable",
                        facts.principal,
                        _ZERO,
                    ),
                    LedgerLine("1920", "Intercompany funding paid", _ZERO, facts.principal),
                )
            else:
                lines = (
                    LedgerLine(
                        "1920", "Intercompany funding received", facts.principal, _ZERO
                    ),
                    LedgerLine("2260", "Intercompany loan payable", _ZERO, facts.principal),
                )
        elif isinstance(facts, CompanyTaxAccrualFacts):
            required_sources = frozenset(
                {LedgerSourceCapability.COMPANY_TAX_FILING}
            )
            primary_source_capability = LedgerSourceCapability.COMPANY_TAX_FILING
            if (
                facts.current_tax.amount < 0
                or facts.deferred_tax_increase.amount < 0
                or facts.current_tax.currency != facts.deferred_tax_increase.currency
                or (
                    facts.current_tax.amount == 0
                    and facts.deferred_tax_increase.amount == 0
                )
            ):
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
            entry_kind = LedgerEntryKind.COMPANY_TAX_ACCRUAL
            memo = "Company tax accrual from versioned tax calculation"
            lines = ()
            if facts.current_tax.amount > 0:
                lines += (
                    LedgerLine("8300", "Current tax expense", facts.current_tax, _ZERO),
                    LedgerLine("2500", "Current tax payable", _ZERO, facts.current_tax),
                )
            if facts.deferred_tax_increase.amount > 0:
                lines += (
                    LedgerLine(
                        "8320",
                        "Increase in deferred tax expense",
                        facts.deferred_tax_increase,
                        _ZERO,
                    ),
                    LedgerLine(
                        "2120",
                        "Deferred tax liability",
                        _ZERO,
                        facts.deferred_tax_increase,
                    ),
                )
        elif isinstance(facts, OrdinaryBankLoanFacts):
            required_sources = frozenset(
                {
                    LedgerSourceCapability.BANKING,
                    LedgerSourceCapability.DOCUMENTS,
                }
            )
            primary_source_capability = LedgerSourceCapability.BANKING
            if len(
                {facts.principal.currency, facts.interest.currency, facts.fee.currency}
            ) != 1 or any(
                amount.amount < 0
                for amount in (facts.principal, facts.interest, facts.fee)
            ):
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
            entry_kind = LedgerEntryKind.BANK_LOAN
            if facts.event is BankLoanEvent.DISBURSEMENT:
                if (
                    facts.principal.amount <= 0
                    or facts.interest.amount != 0
                    or facts.fee.amount != 0
                ):
                    raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
                memo = "Ordinary NOK bank-loan disbursement"
                lines = (
                    LedgerLine("1920", "Bank-loan proceeds", facts.principal, _ZERO),
                    LedgerLine("2220", "Bank-loan principal", _ZERO, facts.principal),
                )
            elif facts.event is BankLoanEvent.PAYMENT:
                total = Money.nok(
                    facts.principal.amount + facts.interest.amount + facts.fee.amount
                )
                _positive(total, "LEDGER_INVALID_INPUT")
                memo = "Allocated ordinary NOK bank-loan payment"
                lines = ()
                if facts.principal.amount > 0:
                    lines += (
                        LedgerLine(
                            "2220", "Bank-loan principal paid", facts.principal, _ZERO
                        ),
                    )
                if facts.interest.amount > 0:
                    lines += (
                        LedgerLine(
                            "8150", "Bank-loan interest", facts.interest, _ZERO
                        ),
                    )
                if facts.fee.amount > 0:
                    lines += (
                        LedgerLine("7770", "Bank-loan fee", facts.fee, _ZERO),
                    )
                lines += (LedgerLine("1920", "Paid from bank", _ZERO, total),)
            else:
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        elif isinstance(facts, CashCapitalIncreaseFacts):
            primary_source_capability = LedgerSourceCapability.CORPORATE_GOVERNANCE
            if (
                facts.nominal_increase.amount <= 0
                or facts.share_premium.amount < 0
                or facts.nominal_increase.currency != facts.share_premium.currency
            ):
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
            total = Money.nok(
                facts.nominal_increase.amount + facts.share_premium.amount
            )
            entry_kind = LedgerEntryKind.CAPITAL_INCREASE
            if facts.phase is CapitalIncreasePhase.BINDING_SUBSCRIPTION:
                required_sources = frozenset(
                    {
                        LedgerSourceCapability.CORPORATE_GOVERNANCE,
                        LedgerSourceCapability.DOCUMENTS,
                    }
                )
                memo = "Binding cash-capital subscription"
                lines = (
                    LedgerLine("1500", "Subscription receivable", total, _ZERO),
                    LedgerLine(
                        "2030", "Unregistered capital increase", _ZERO, total
                    ),
                )
            elif facts.phase is CapitalIncreasePhase.RESTRICTED_PAYMENT:
                required_sources = frozenset(
                    {
                        LedgerSourceCapability.BANKING,
                        LedgerSourceCapability.CORPORATE_GOVERNANCE,
                        LedgerSourceCapability.DOCUMENTS,
                    }
                )
                memo = "Cash contribution paid to restricted account"
                lines = (
                    LedgerLine("1921", "Restricted contribution bank", total, _ZERO),
                    LedgerLine("1500", "Subscription receivable", _ZERO, total),
                )
            elif facts.phase is CapitalIncreasePhase.REGISTERED:
                required_sources = frozenset(
                    {
                        LedgerSourceCapability.BANKING,
                        LedgerSourceCapability.CORPORATE_GOVERNANCE,
                        LedgerSourceCapability.DOCUMENTS,
                        LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING,
                    }
                )
                memo = "Registered cash-capital increase"
                lines = (
                    LedgerLine("2030", "Unregistered capital increase", total, _ZERO),
                    LedgerLine(
                        "2000", "Registered share capital", _ZERO, facts.nominal_increase
                    ),
                )
                if facts.share_premium.amount > 0:
                    lines += (
                        LedgerLine("2020", "Share premium", _ZERO, facts.share_premium),
                    )
                lines += (
                    LedgerLine("1920", "Released contribution bank", total, _ZERO),
                    LedgerLine("1921", "Restricted contribution bank", _ZERO, total),
                )
            else:
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        elif isinstance(facts, ApprovedLossCoverageCapitalReductionFacts):
            primary_source_capability = LedgerSourceCapability.CORPORATE_GOVERNANCE
            _positive(facts.nominal_reduction, "LEDGER_INVALID_INPUT")
            entry_kind = LedgerEntryKind.CAPITAL_REDUCTION
            if (
                facts.recognition
                is CapitalReductionRecognition.DECIDED_NOT_REGISTERED
            ):
                required_sources = frozenset(
                    {
                        LedgerSourceCapability.CORPORATE_GOVERNANCE,
                        LedgerSourceCapability.DOCUMENTS,
                    }
                )
                memo = "Loss-coverage capital reduction decided, not registered"
                lines = (
                    LedgerLine(
                        "2033",
                        "Unregistered capital reduction",
                        facts.nominal_reduction,
                        _ZERO,
                    ),
                    LedgerLine(
                        "2080", "Uncovered loss", _ZERO, facts.nominal_reduction
                    ),
                )
            elif facts.recognition is CapitalReductionRecognition.REGISTERED:
                required_sources = frozenset(
                    {
                        LedgerSourceCapability.CORPORATE_GOVERNANCE,
                        LedgerSourceCapability.DOCUMENTS,
                        LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING,
                    }
                )
                memo = "Loss-coverage capital reduction registered"
                lines = (
                    LedgerLine(
                        "2000",
                        "Registered share capital",
                        facts.nominal_reduction,
                        _ZERO,
                    ),
                    LedgerLine(
                        "2033",
                        "Unregistered capital reduction",
                        _ZERO,
                        facts.nominal_reduction,
                    ),
                )
            elif (
                facts.recognition
                is CapitalReductionRecognition.FIRST_RECOGNIZED_AFTER_REGISTRATION
            ):
                required_sources = frozenset(
                    {
                        LedgerSourceCapability.CORPORATE_GOVERNANCE,
                        LedgerSourceCapability.DOCUMENTS,
                        LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING,
                    }
                )
                memo = "Registered loss-coverage capital reduction first recognized"
                lines = (
                    LedgerLine(
                        "2000",
                        "Registered share capital",
                        facts.nominal_reduction,
                        _ZERO,
                    ),
                    LedgerLine(
                        "2080", "Uncovered loss", _ZERO, facts.nominal_reduction
                    ),
                )
            else:
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        elif isinstance(facts, GroupContributionFacts):
            required_sources = frozenset(
                {
                    LedgerSourceCapability.CORPORATE_GOVERNANCE,
                    LedgerSourceCapability.COMPANY_TAX_FILING,
                }
            )
            primary_source_capability = LedgerSourceCapability.CORPORATE_GOVERNANCE
            amounts = (
                facts.gross_tax_amount,
                facts.related_tax,
                facts.after_tax_accounting_amount,
            )
            if (
                any(amount.amount < 0 for amount in amounts)
                or len({amount.currency for amount in amounts}) != 1
                or facts.gross_tax_amount.amount
                != facts.related_tax.amount + facts.after_tax_accounting_amount.amount
                or facts.after_tax_accounting_amount.amount <= 0
            ):
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
            if (
                facts.relationship
                is GroupContributionRelationship.SUBSIDIARY_TO_PARENT
                and not facts.post_acquisition_income_proved
            ) or (
                facts.relationship
                is GroupContributionRelationship.PARENT_TO_SUBSIDIARY
                and not facts.impairment_cleared
            ):
                raise LedgerError.precondition_failed("LEDGER_INVALID_INPUT")
            amount = facts.after_tax_accounting_amount
            entry_kind = LedgerEntryKind.GROUP_CONTRIBUTION
            memo = f"Supported group contribution: {facts.relationship.value}"
            if facts.perspective is GroupContributionPerspective.GIVER:
                debit_account = (
                    "1300"
                    if facts.relationship
                    is GroupContributionRelationship.PARENT_TO_SUBSIDIARY
                    else "2050"
                )
                debit_description = (
                    "Increase in subsidiary investment"
                    if debit_account == "1300"
                    else "Group contribution against other equity"
                )
                lines = (
                    LedgerLine(debit_account, debit_description, amount, _ZERO),
                    LedgerLine("2960", "Group contribution payable", _ZERO, amount),
                )
            else:
                credit_account = (
                    "8075"
                    if facts.relationship
                    is GroupContributionRelationship.SUBSIDIARY_TO_PARENT
                    else "2035"
                )
                credit_description = (
                    "Income from subsidiary"
                    if credit_account == "8075"
                    else "Other paid-in equity"
                )
                lines = (
                    LedgerLine("1560", "Group contribution receivable", amount, _ZERO),
                    LedgerLine(credit_account, credit_description, _ZERO, amount),
                )
        else:
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")

        allows_evidence_pack = isinstance(
            facts,
            (
                InvestmentPurchaseRecognitionFacts,
                InvestmentSaleRecognitionFacts,
                InvestmentFundDistributionRecognitionFacts,
            ),
        ) or (
            isinstance(facts, InvestmentDividendFacts)
            and facts.phase is InvestmentDividendPhase.FINAL_DECISION
        )
        actual_sources = frozenset(source.capability for source in sources)
        if (
            command.primary_source.capability is not primary_source_capability
            or actual_sources != required_sources
            or (
                not allows_evidence_pack
                and len(sources) != len(required_sources)
            )
        ):
            raise LedgerError.precondition_failed(
                "LEDGER_SOURCE_CAPABILITY_MISMATCH"
            )
        _balanced(lines)
        if isinstance(facts, InvestmentDividendFacts):
            if facts.phase is InvestmentDividendPhase.FINAL_DECISION:
                return await self._persistence.record_received_dividend_decision(
                    command,
                    memo=memo,
                    lines=lines,
                )
            decision_reference = (
                facts.decision_entry_id or facts.decision_reference_id
            )
            if decision_reference is None:  # narrowed above
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
            return await self._persistence.record_received_dividend_payment(
                command,
                decision_reference=decision_reference,
                memo=memo,
                lines=lines,
            )
        if isinstance(facts, OrdinaryBankLoanFacts):
            if facts.event is BankLoanEvent.DISBURSEMENT:
                return await self._persistence.record_bank_loan_disbursement(
                    command,
                    loan_reference_id=facts.loan_reference_id,
                    principal=facts.principal,
                    memo=memo,
                    lines=lines,
                )
            if facts.event is not BankLoanEvent.PAYMENT:
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
            return await self._persistence.record_bank_loan_payment(
                command,
                loan_reference_id=facts.loan_reference_id,
                principal=facts.principal,
                interest=facts.interest,
                fee=facts.fee,
                memo=memo,
                lines=lines,
            )
        if isinstance(facts, CashCapitalIncreaseFacts):
            if facts.phase is CapitalIncreasePhase.BINDING_SUBSCRIPTION:
                return await self._persistence.record_cash_capital_increase_subscription(
                    command,
                    capital_increase_reference_id=(
                        facts.capital_increase_reference_id
                    ),
                    nominal_increase=facts.nominal_increase,
                    share_premium=facts.share_premium,
                    memo=memo,
                    lines=lines,
                )
            if facts.phase is CapitalIncreasePhase.RESTRICTED_PAYMENT:
                return await self._persistence.record_cash_capital_increase_restricted_payment(
                    command,
                    capital_increase_reference_id=(
                        facts.capital_increase_reference_id
                    ),
                    nominal_increase=facts.nominal_increase,
                    share_premium=facts.share_premium,
                    memo=memo,
                    lines=lines,
                )
            if facts.phase is CapitalIncreasePhase.REGISTERED:
                return await self._persistence.record_cash_capital_increase_registration(
                    command,
                    capital_increase_reference_id=(
                        facts.capital_increase_reference_id
                    ),
                    nominal_increase=facts.nominal_increase,
                    share_premium=facts.share_premium,
                    memo=memo,
                    lines=lines,
                )
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        if isinstance(facts, ApprovedLossCoverageCapitalReductionFacts):
            if (
                facts.recognition
                is CapitalReductionRecognition.DECIDED_NOT_REGISTERED
            ):
                return await self._persistence.record_loss_coverage_capital_reduction_decision(
                    command,
                    capital_reduction_reference_id=(
                        facts.capital_reduction_reference_id
                    ),
                    nominal_reduction=facts.nominal_reduction,
                    memo=memo,
                    lines=lines,
                )
            if facts.recognition is CapitalReductionRecognition.REGISTERED:
                return await self._persistence.record_loss_coverage_capital_reduction_registration(
                    command,
                    capital_reduction_reference_id=(
                        facts.capital_reduction_reference_id
                    ),
                    nominal_reduction=facts.nominal_reduction,
                    memo=memo,
                    lines=lines,
                )
            if (
                facts.recognition
                is CapitalReductionRecognition.FIRST_RECOGNIZED_AFTER_REGISTRATION
            ):
                return await self._persistence.record_loss_coverage_capital_reduction_direct_registration(
                    command,
                    capital_reduction_reference_id=(
                        facts.capital_reduction_reference_id
                    ),
                    nominal_reduction=facts.nominal_reduction,
                    memo=memo,
                    lines=lines,
                )
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        return await self._persistence.post_entry(
            command,
            entry_kind=entry_kind,
            memo=memo,
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=command.primary_source.capability,
            source_record_id=command.primary_source.record_id,
        )

    async def record_reconstruction_assessment(
        self, command: RecordReconstructionAssessmentCommand
    ) -> ReconstructionAssessment:
        if command.as_of.value.year != int(command.income_year):
            raise LedgerError.invalid_input("LEDGER_RECONSTRUCTION_COVERAGE_INVALID")
        economic_fact_ids = tuple(
            sorted(command.economic_fact_entry_ids, key=lambda entry_id: entry_id.value)
        )
        if len({entry_id.value for entry_id in economic_fact_ids}) != len(
            economic_fact_ids
        ):
            raise LedgerError.invalid_input(
                "LEDGER_RECONSTRUCTION_ECONOMIC_FACTS_INVALID"
            )
        by_requirement = {(item.kind, item.issuer): item for item in command.evidence}
        if len(by_requirement) != len(command.evidence):
            raise LedgerError.invalid_input("LEDGER_RECONSTRUCTION_EVIDENCE_DUPLICATE")
        if set(by_requirement) != set(_RECONSTRUCTION_EVIDENCE_REQUIREMENTS):
            raise LedgerError.precondition_failed(
                "LEDGER_RECONSTRUCTION_EVIDENCE_INCOMPLETE"
            )
        if any(
            item.gap_code is not None
            and item.gap_code is not _RECONSTRUCTION_GAP_BY_KIND[item.kind]
            for item in by_requirement.values()
        ):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        year_start = date(int(command.income_year), 1, 1)
        for kind in _FULL_YEAR_COVERAGE_EVIDENCE:
            matching = tuple(
                item for item in by_requirement.values() if item.kind is kind
            )
            if any(
                item.coverage_from is None
                or item.coverage_through is None
                or item.coverage_from.value != year_start
                or item.coverage_through.value != command.as_of.value
                for item in matching
            ):
                raise LedgerError.precondition_failed(
                    "LEDGER_RECONSTRUCTION_COVERAGE_INVALID"
                )
        evidence = tuple(
            by_requirement[requirement]
            for requirement in _RECONSTRUCTION_EVIDENCE_REQUIREMENTS
        )
        gap_codes = tuple(
            item.gap_code
            for item in evidence
            if item.confirmation is not ReconstructionEvidenceStatus.CONFIRMED
            and item.gap_code is not None
        )
        state = ReconstructionState.BLOCKED if gap_codes else ReconstructionState.READY
        return await self._persistence.record_reconstruction_assessment(
            replace(command, economic_fact_entry_ids=economic_fact_ids),
            evidence=evidence,
            state=state,
            gap_codes=gap_codes,
        )

    async def get_reconstruction_assessment(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        correlation_id: CorrelationId,
    ) -> ReconstructionAssessment:
        return await self._persistence.get_reconstruction_assessment(
            actor_id=actor_id,
            company_id=company_id,
            income_year=income_year,
            correlation_id=correlation_id,
        )

    async def rebuild_company_year_opening(
        self, command: RebuildCompanyYearOpeningCommand
    ) -> PostedLedgerEntry:
        expected_basis = (
            LedgerSourceCapability.ANNUAL_ACCOUNTS_FILING
            if command.mode is OpeningPositionMode.PRIOR_CLOSE_RECONSTRUCTION
            else LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING
        )
        if command.opening_basis.capability is not expected_basis:
            raise LedgerError.precondition_failed("LEDGER_OPENING_EVIDENCE_INVALID")
        expanded = tuple(
            compiled
            for component in command.components
            for compiled in _opening_expansion(component, mode=command.mode)
        )
        if command.mode is OpeningPositionMode.NEW_COMPANY:
            opening_basis_identity = (
                command.opening_basis.capability,
                command.opening_basis.record_id,
                command.opening_basis.revision,
                command.opening_basis.fact_sha256,
            )
            ledger_sources = set()
            for component in expanded:
                sources = (
                    component.primary_source,
                    *component.corroborating_sources,
                )
                source_identities = {
                    (
                        source.capability,
                        source.record_id,
                        source.revision,
                        source.fact_sha256,
                    )
                    for source in sources
                }
                if opening_basis_identity not in source_identities:
                    raise LedgerError.precondition_failed(
                        "LEDGER_OPENING_EVIDENCE_INVALID"
                    )
                ledger_sources.update(
                    identity
                    for identity in source_identities
                    if identity[0] is LedgerSourceCapability.LEDGER
                )
            if len(ledger_sources) != 1:
                raise LedgerError.precondition_failed(
                    "LEDGER_OPENING_EVIDENCE_INVALID"
                )
        components = tuple(
            sorted(
                expanded,
                key=lambda component: (
                    component.category.value,
                    component.reference_id,
                    component.component_kind,
                ),
            )
        )
        identities = {
            (component.category, component.reference_id) for component in components
        }
        if len(identities) != len(components):
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        lines: list[LedgerLine] = []
        entry_sources = [command.opening_basis]
        seen_sources = {
            (
                command.opening_basis.capability,
                command.opening_basis.record_id,
                command.opening_basis.revision,
            )
        }
        for component in components:
            component_sources = (
                component.primary_source,
                *component.corroborating_sources,
            )
            for source in component_sources:
                identity = (source.capability, source.record_id, source.revision)
                if identity not in seen_sources:
                    seen_sources.add(identity)
                    entry_sources.append(source)
            lines.append(
                LedgerLine(
                    component.account,
                    f"{component.description}: {component.reference_id}",
                    component.amount if component.is_debit else _ZERO,
                    _ZERO if component.is_debit else component.amount,
                )
            )
        canonical_lines = tuple(lines)
        _balanced(canonical_lines)
        return await self._persistence.rebuild_company_year_opening(
            command,
            components=components,
            lines=canonical_lines,
            entry_sources=tuple(entry_sources),
        )

    async def post_administrative_cost(
        self, command: PostAdministrativeCostCommand
    ) -> PostedLedgerEntry:
        _positive(command.amount, "LEDGER_ADMINISTRATIVE_COST_NOT_POSITIVE")
        if command.paid_date.value.year != int(command.income_year):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        payee = command.payee.strip()
        if not payee:
            raise LedgerError.invalid_input("LEDGER_PAYEE_REQUIRED")
        document = f" (document {command.document_id})" if command.document_id else ""
        lines = _administrative_cost_lines(
            command.category,
            command.amount,
            description=f"Admin cost: {payee}",
        )
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.ADMINISTRATIVE_COST,
            memo=(
                f"Admin cost paid to {payee} on {command.paid_date.value.isoformat()}"
                f"{document}"
            ),
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.BANKING,
            source_record_id=command.bank_transaction_id,
        )

    async def post_bank_suggestion_outcome(
        self, command: PostBankSuggestionOutcomeCommand
    ) -> PostedLedgerEntry:
        _positive(command.amount, "LEDGER_INVALID_INPUT")
        account, description, is_income = _BANK_SUGGESTION_LINES[command.rule]
        lines = (
            (
                LedgerLine("1920", "Bank", command.amount, _ZERO),
                LedgerLine(account, description, _ZERO, command.amount),
            )
            if is_income
            else (
                LedgerLine(account, description, command.amount, _ZERO),
                LedgerLine("1920", "Bank", _ZERO, command.amount),
            )
        )
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.BANK_RULE_SUGGESTION,
            memo=f"Godkjent bankforslag: {command.transaction_text}",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.BANKING,
            source_record_id=command.acceptance_id,
        )

    async def post_received_dividend(
        self, command: PostReceivedDividendCommand
    ) -> PostedLedgerEntry:
        _positive(command.gross_amount, "LEDGER_INVALID_INPUT")
        lines = (
            LedgerLine(
                "1920", "Dividend received in bank", command.gross_amount, _ZERO
            ),
            LedgerLine(
                "8070",
                f"Dividend from {command.paying_company_name}",
                _ZERO,
                command.gross_amount,
            ),
        )
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.DIVIDEND_RECEIVED,
            memo=f"Dividend received from {command.paying_company_name}",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.INVESTMENTS,
            source_record_id=command.action_id,
        )

    async def post_received_fund_distribution(
        self, command: PostReceivedFundDistributionCommand
    ) -> PostedLedgerEntry:
        _positive(command.gross_amount, "LEDGER_INVALID_INPUT")
        if (
            command.dividend_portion.amount < 0
            or command.interest_portion.amount < 0
            or command.dividend_portion.amount + command.interest_portion.amount
            != command.gross_amount.amount
        ):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        lines = [
            LedgerLine(
                "1920", "Fund distribution received in bank", command.gross_amount, _ZERO
            )
        ]
        if command.dividend_portion.amount:
            lines.append(LedgerLine(
                "8070",
                f"Fund dividend from {command.fund_name}",
                _ZERO,
                command.dividend_portion,
            ))
        if command.interest_portion.amount:
            lines.append(LedgerLine(
                "8050",
                f"Fund interest income from {command.fund_name}",
                _ZERO,
                command.interest_portion,
            ))
        balanced_lines = tuple(lines)
        _balanced(balanced_lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.DIVIDEND_RECEIVED,
            memo=f"Fund distribution received from {command.fund_name}",
            lines=balanced_lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.INVESTMENTS,
            source_record_id=command.action_id,
        )

    async def post_investment_purchase(
        self, command: PostInvestmentPurchaseCommand
    ) -> PostedLedgerEntry:
        _positive(command.purchase_amount, "LEDGER_INVALID_INPUT")
        account = _INVESTMENT_ACCOUNTS.get(command.classification)
        if account is None:
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        lines = (
            LedgerLine(
                account,
                f"Investment in {command.investment_name}",
                command.purchase_amount,
                _ZERO,
            ),
            LedgerLine("1920", "Paid from bank", _ZERO, command.purchase_amount),
        )
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.SHARE_PURCHASE,
            memo=f"Share purchase: {command.investment_name}",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.INVESTMENTS,
            source_record_id=command.action_id,
        )

    async def post_investment_sale(
        self, command: PostInvestmentSaleCommand
    ) -> PostedLedgerEntry:
        _positive(command.proceeds, "LEDGER_INVALID_INPUT")
        if command.fifo_cost_basis_reduction.amount < 0:
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        if command.proceeds.currency != command.fifo_cost_basis_reduction.currency:
            raise LedgerError.invalid_input("LEDGER_CURRENCY_MISMATCH")
        account = _INVESTMENT_ACCOUNTS.get(command.classification)
        if account is None:
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        gain_or_loss = (
            command.proceeds.amount - command.fifo_cost_basis_reduction.amount
        )
        lines = (
            LedgerLine(
                "1920", "Sale proceeds received in bank", command.proceeds, _ZERO
            ),
            LedgerLine(
                account,
                f"Cost basis reduction: {command.investment_name}",
                _ZERO,
                command.fifo_cost_basis_reduction,
            ),
        )
        if gain_or_loss > 0:
            lines += (
                LedgerLine(
                    "8071",
                    f"Share sale gain: {command.investment_name}",
                    _ZERO,
                    Money.nok(gain_or_loss),
                ),
            )
        elif gain_or_loss < 0:
            lines += (
                LedgerLine(
                    "8171",
                    f"Share sale loss: {command.investment_name}",
                    Money.nok(abs(gain_or_loss)),
                    _ZERO,
                ),
            )
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.SHARE_SALE,
            memo=f"Share sale: {command.investment_name}",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.INVESTMENTS,
            source_record_id=command.action_id,
        )

    async def post_owner_dividend_declared(
        self, command: PostOwnerDividendDeclaredCommand
    ) -> PostedLedgerEntry:
        _positive(command.declared_amount, "LEDGER_INVALID_INPUT")
        if not command.accounting_policy_version.strip():
            raise LedgerError.precondition_failed(
                "LEDGER_OWNER_DIVIDEND_ACCOUNTING_POLICY_NOT_APPROVED"
            )
        lines = (
            LedgerLine(
                command.declaration_debit_account,
                "Declared dividend to owners",
                command.declared_amount,
                _ZERO,
            ),
            LedgerLine(
                command.dividend_payable_account,
                "Dividend payable to owners",
                _ZERO,
                command.declared_amount,
            ),
        )
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.OWNER_DIVIDEND_DECLARED,
            memo="Declared owner dividend from finalized corporate decision",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.CORPORATE_GOVERNANCE,
            source_record_id=command.finalization_id,
            requested_entry_id=command.ledger_entry_id,
        )

    async def post_owner_dividend_payment(
        self, command: PostOwnerDividendPaymentCommand
    ) -> PostedLedgerEntry:
        _positive(command.payment_amount, "LEDGER_INVALID_INPUT")
        if not command.accounting_policy_version.strip():
            raise LedgerError.precondition_failed(
                "LEDGER_OWNER_DIVIDEND_ACCOUNTING_POLICY_NOT_APPROVED"
            )
        lines = (
            LedgerLine(
                command.dividend_payable_account,
                "Dividend payable cleared",
                command.payment_amount,
                _ZERO,
            ),
            LedgerLine(
                command.bank_account,
                "Dividend paid from bank",
                _ZERO,
                command.payment_amount,
            ),
        )
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.OWNER_DIVIDEND_PAYMENT,
            memo="Payment of finalized owner dividend payable",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.CORPORATE_GOVERNANCE,
            source_record_id=command.payment_event_id,
            requested_entry_id=command.ledger_entry_id,
        )

    async def post_shareholder_loan(
        self, command: PostShareholderLoanCommand
    ) -> PostedLedgerEntry:
        _positive(command.amount, "LEDGER_INVALID_INPUT")
        if command.direction is ShareholderLoanDirection.SHAREHOLDER_TO_COMPANY:
            lines = _owner_loan_funding_lines(
                command.amount,
                counterparty_name=command.counterparty_name,
            )
        else:
            lines = (
                LedgerLine(
                    "1370",
                    f"Loan receivable from {command.counterparty_name}",
                    command.amount,
                    _ZERO,
                ),
                LedgerLine(
                    "1920",
                    f"Loan paid to {command.counterparty_name}",
                    _ZERO,
                    command.amount,
                ),
            )
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.SHAREHOLDER_LOAN,
            memo=f"Shareholder loan: {command.counterparty_name}",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.CORPORATE_GOVERNANCE,
            source_record_id=command.action_id,
            requested_entry_id=command.ledger_entry_id,
        )

    async def post_tax_settlement(
        self, command: PostTaxSettlementCommand
    ) -> PostedLedgerEntry:
        _positive(command.amount, "LEDGER_INVALID_INPUT")
        lines = tax_settlement_preview_lines(command.settlement_kind, command.amount)
        _balanced(lines)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.TAX_SETTLEMENT,
            memo=f"Skatteoppgjør: {command.settlement_kind.value}",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=LedgerSourceCapability.COMPANY_TAX_FILING,
            source_record_id=command.settlement_id,
        )

    async def post_manual_journal(
        self, command: PostManualJournalCommand
    ) -> PostedLedgerEntry:
        memo = command.memo.strip()
        if not memo:
            raise LedgerError.invalid_input("LEDGER_MEMO_REQUIRED")
        _balanced(command.lines)
        risk_flags = tuple(
            LedgerRiskFlag(
                LedgerRiskCode.MANUAL_JOURNAL_SENSITIVE_ACCOUNT,
                account,
            )
            for account in sorted(
                {line.account for line in command.lines} & _SENSITIVE_MANUAL_ACCOUNTS
            )
        )
        if risk_flags and not command.warning_accepted:
            raise LedgerError.precondition_failed("LEDGER_WARNING_ACCEPTANCE_REQUIRED")
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.MANUAL_JOURNAL,
            memo=memo,
            lines=command.lines,
            risk_flags=risk_flags,
            warning_accepted=command.warning_accepted,
            source_capability=LedgerSourceCapability.LEDGER,
            source_record_id=LedgerSourceRecordId(str(command.idempotency_key)),
        )

    async def lock_period(self, command: LockPeriodCommand) -> PeriodLock:
        if not command.reason.strip():
            raise LedgerError.invalid_input("LEDGER_LOCK_REASON_REQUIRED")
        return await self._persistence.lock_period(command)

    async def list_entry_amendments(
        self, *, actor_id: ActorId, company_id: CompanyId, correlation_id: CorrelationId,
    ) -> tuple[LedgerEntryAmendment, ...]:
        return await self._persistence.list_entry_amendments(
            actor_id=actor_id, company_id=company_id, correlation_id=correlation_id,
        )

    async def list_entries(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> LedgerEntryPage:
        if not 1 <= limit <= 100:
            raise LedgerError.invalid_input("LEDGER_PAGE_LIMIT_INVALID")
        if not company_ids or len(company_ids) > 100:
            raise LedgerError.invalid_input("LEDGER_COMPANY_SCOPE_INVALID")
        return await self._persistence.list_entries(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )

    async def list_period_locks(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> PeriodLockPage:
        if not 1 <= limit <= 100:
            raise LedgerError.invalid_input("LEDGER_PAGE_LIMIT_INVALID")
        if not company_ids or len(company_ids) > 100:
            raise LedgerError.invalid_input("LEDGER_COMPANY_SCOPE_INVALID")
        return await self._persistence.list_period_locks(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )


def tax_settlement_preview_lines(
    settlement_kind: TaxSettlementKind, amount: Money
) -> tuple[LedgerLine, ...]:
    """Ledger-owned presentation; zero is a preview only, never a valid posting."""
    if settlement_kind is TaxSettlementKind.PAYABLE:
        lines = (
            LedgerLine("8300", "Skattekostnad", amount, _ZERO),
            LedgerLine("2500", "Betalbar skatt", _ZERO, amount),
        )
    elif settlement_kind is TaxSettlementKind.REFUND:
        lines = (
            LedgerLine(
                "1920", "Skatterefusjon mottatt", amount, _ZERO
            ),
            LedgerLine("1570", "Skatt til gode", _ZERO, amount),
        )
    else:
        lines = (
            LedgerLine("2500", "Betalt skatt", amount, _ZERO),
            LedgerLine("1920", "Bank", _ZERO, amount),
        )
    return lines
