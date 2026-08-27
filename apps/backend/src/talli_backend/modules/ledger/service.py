"""Narrow-ledger business invariants and intent-specific posting policy."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from talli_backend.modules.ledger.public import (
    AdministrativeCostCategory,
    AdministrativeCostCorrectionScope,
    ApprovedOneSidedIntercompanyLoanFundingFacts,
    ApprovedLossCoverageCapitalReductionFacts,
    ApprovedOwnerLoanFundingFacts,
    BankInterestIncomeFacts,
    BankLoanEvent,
    BankSuggestionRule,
    CashCapitalIncreaseFacts,
    CapitalIncreasePhase,
    CapitalReductionRecognition,
    CloseCompanyYearCommand,
    CompanyTaxAccrualFacts,
    CompanyYearCloseAssessment,
    CompanyYearCloseEvidence,
    CompanyYearCloseEvidenceKind,
    CompanyYearCloseGapCode,
    CompanyYearCloseOutputKind,
    CompanyYearCloseState,
    CorrectHoldingActionCommand,
    CorrectedLedgerEntries,
    GroupContributionFacts,
    GroupContributionPerspective,
    GroupContributionRelationship,
    IntercompanyLoanPerspective,
    IntercompanyLoanRelationship,
    InvestmentDividendFacts,
    InvestmentDividendPhase,
    LedgerCursor,
    LedgerEntryKind,
    LedgerError,
    LedgerLine,
    LedgerPersistence,
    LedgerRiskCode,
    LedgerRiskFlag,
    LedgerSourceCapability,
    LedgerSourceRecordId,
    LedgerEntryPage,
    LockPeriodCommand,
    OrdinaryBankLoanFacts,
    PeriodLock,
    PeriodLockPage,
    PostAdministrativeCostCommand,
    PostBankSuggestionOutcomeCommand,
    PostInvestmentDividendCommand,
    PostInvestmentPurchaseCommand,
    PostInvestmentSaleCommand,
    PostOwnerDividendDeclaredCommand,
    PostOwnerDividendPaymentCommand,
    PostShareholderLoanCommand,
    PostTaxSettlementCommand,
    ReconstructionAssessment,
    ReconstructionEvidence,
    ReconstructionEvidenceIssuer,
    ReconstructionEvidenceKind,
    ReconstructionEvidenceStatus,
    ReconstructionGapCode,
    ReconstructionState,
    RecognizeHoldingActionCommand,
    RecordReconstructionAssessmentCommand,
    ShareholderLoanDirection,
    TaxSettlementKind,
    PostedLedgerEntry,
    PostManualJournalCommand,
    PostOpeningBalanceCommand,
)
from talli_backend.shared.kernel import ActorId, CompanyId, CorrelationId, Money


_ZERO = Money.nok("0.00")
_SENSITIVE_MANUAL_ACCOUNTS = frozenset(
    {"1370", "1800", "2000", "2050", "2255", "2800", "8070", "8090"}
)
_ADMINISTRATIVE_COST_ACCOUNTS = {
    AdministrativeCostCategory.BANK_FEE: "7770",
    AdministrativeCostCategory.ACCOUNTING_FEE: "6705",
    AdministrativeCostCategory.SOFTWARE: "6420",
    AdministrativeCostCategory.PUBLIC_FEE: "7790",
    AdministrativeCostCategory.LEGAL_ADVISORY: "6720",
    AdministrativeCostCategory.OTHER_ADMIN_COST: "7795",
}


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
_FULL_YEAR_COVERAGE_EVIDENCE = frozenset(
    {
        ReconstructionEvidenceKind.BANK_MOVEMENTS,
        ReconstructionEvidenceKind.CURRENT_YEAR_ACTIVITY,
    }
)
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
            or any(
                item.ledger_state_digest != current.ledger_state_digest
                for item in canonical
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
                if facts.decision_entry_id is not None:
                    raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
                required_sources = frozenset(
                    {
                        LedgerSourceCapability.INVESTMENTS,
                        LedgerSourceCapability.DOCUMENTS,
                        LedgerSourceCapability.COMPANY_TAX_FILING,
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
                if facts.decision_entry_id is None:
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
            required_sources = frozenset(
                {LedgerSourceCapability.CORPORATE_GOVERNANCE}
            )
            primary_source_capability = LedgerSourceCapability.CORPORATE_GOVERNANCE
            _positive(facts.nominal_reduction, "LEDGER_INVALID_INPUT")
            entry_kind = LedgerEntryKind.CAPITAL_REDUCTION
            if (
                facts.recognition
                is CapitalReductionRecognition.DECIDED_NOT_REGISTERED
            ):
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
            else:
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

        actual_sources = frozenset(source.capability for source in sources)
        if (
            command.primary_source.capability is not primary_source_capability
            or actual_sources != required_sources
            or len(sources) != len(required_sources)
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
            decision_entry_id = facts.decision_entry_id
            if decision_entry_id is None:  # narrowed above; keep the port call typed.
                raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
            return await self._persistence.record_received_dividend_payment(
                command,
                decision_entry_id=decision_entry_id,
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
            command,
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

    async def post_opening_balance(
        self, command: PostOpeningBalanceCommand
    ) -> PostedLedgerEntry:
        if command.bank_balance.amount < 0 or command.share_capital_snapshot.amount < 0:
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_NEGATIVE")
        if command.bank_balance.currency != command.share_capital_snapshot.currency:
            raise LedgerError.invalid_input("LEDGER_CURRENCY_MISMATCH")
        retained = command.bank_balance.amount - command.share_capital_snapshot.amount
        retained_debit = Money.nok(str(abs(retained))) if retained < 0 else _ZERO
        retained_credit = Money.nok(str(retained)) if retained > 0 else _ZERO
        lines = (
            LedgerLine("1920", "Bankinnskudd", command.bank_balance, _ZERO),
            LedgerLine("2000", "Aksjekapital", _ZERO, command.share_capital_snapshot),
            LedgerLine(
                "2050",
                "Annen egenkapital" if retained >= 0 else "Udekket tap",
                retained_debit,
                retained_credit,
            ),
        )
        _balanced(lines, permit_zero_line=True)
        return await self._persistence.post_entry(
            command,
            entry_kind=LedgerEntryKind.OPENING_BALANCE,
            memo="Åpningsbalanse for Talli-start",
            lines=lines,
            risk_flags=(),
            warning_accepted=False,
            source_capability=(
                LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING
                if command.opening_snapshot_id is not None
                else LedgerSourceCapability.LEDGER
            ),
            source_record_id=command.opening_snapshot_id
            or LedgerSourceRecordId(str(command.idempotency_key)),
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

    async def post_investment_dividend(
        self, command: PostInvestmentDividendCommand
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

    async def post_investment_purchase(
        self, command: PostInvestmentPurchaseCommand
    ) -> PostedLedgerEntry:
        _positive(command.purchase_amount, "LEDGER_INVALID_INPUT")
        lines = (
            LedgerLine(
                "1800",
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
        gain_or_loss = (
            command.proceeds.amount - command.fifo_cost_basis_reduction.amount
        )
        lines = (
            LedgerLine(
                "1920", "Sale proceeds received in bank", command.proceeds, _ZERO
            ),
            LedgerLine(
                "1800",
                f"Cost basis reduction: {command.investment_name}",
                _ZERO,
                command.fifo_cost_basis_reduction,
            ),
        )
        if gain_or_loss > 0:
            lines += (
                LedgerLine(
                    "8070",
                    f"Share sale gain: {command.investment_name}",
                    _ZERO,
                    Money.nok(gain_or_loss),
                ),
            )
        elif gain_or_loss < 0:
            lines += (
                LedgerLine(
                    "8090",
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
        )

    async def post_tax_settlement(
        self, command: PostTaxSettlementCommand
    ) -> PostedLedgerEntry:
        _positive(command.amount, "LEDGER_INVALID_INPUT")
        if command.settlement_kind is TaxSettlementKind.PAYABLE:
            lines = (
                LedgerLine("8300", "Skattekostnad", command.amount, _ZERO),
                LedgerLine("2500", "Betalbar skatt", _ZERO, command.amount),
            )
        elif command.settlement_kind is TaxSettlementKind.REFUND:
            lines = (
                LedgerLine(
                    "1920", "Skatterefusjon mottatt", command.amount, _ZERO
                ),
                LedgerLine("1570", "Skatt til gode", _ZERO, command.amount),
            )
        else:
            lines = (
                LedgerLine("2500", "Betalt skatt", command.amount, _ZERO),
                LedgerLine("1920", "Bank", _ZERO, command.amount),
            )
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
