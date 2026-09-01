"""Private, versioned policy for supported domestic investment patterns."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
import json
import re

from talli_backend.modules.investments.public import (
    AccountingEntryReference,
    CorrectInvestmentCommand,
    InvestmentAccountingClassification,
    InvestmentDocumentStatus,
    InvestmentEvidenceMode,
    InvestmentKind,
    InvestmentActivityKind,
    InvestmentPolicyVersion,
    InvestmentSaleLotCalculation,
    InvestmentTaxTreatment,
    InvestmentsError,
    InvestmentsPersistence,
    PreparedReceivedDividend,
    PreparedReceivedFundDistribution,
    PreparedInvestmentCorrection,
    PreparedSharePurchase,
    PreparedShareSale,
    RecordReceivedDividendCommand,
    RecordReceivedFundDistributionCommand,
    RecordSharePurchaseCommand,
    RecordShareSaleCommand,
    RecordedReceivedDividend,
    RecordedReceivedFundDistribution,
    RecordedInvestmentCorrection,
    RecordedSharePurchase,
    RecordedShareSale,
)
from talli_backend.shared.kernel import Money


_PRIVATE_CLASSIFICATIONS = frozenset(
    {
        InvestmentAccountingClassification.SUBSIDIARY,
        InvestmentAccountingClassification.ASSOCIATE,
        InvestmentAccountingClassification.OTHER_LONG_TERM,
    }
)
_POLICY_VERSION = InvestmentPolicyVersion.DOMESTIC_2026_V1
_ZERO = Money.nok("0")


def _source_value(value: object | None) -> str | None:
    return str(value) if value is not None else None


def _canonical_digest(payload: object) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _evidence_digest(command: object) -> str:
    return _canonical_digest(
        {
            "bankTransactionId": _source_value(command.bank_transaction_id),
            "documentId": _source_value(command.document_id),
            "documentStatus": command.document_status.value,
            "evidenceMode": command.evidence_mode.value,
            "evidenceReference": command.evidence_reference,
            "ownerAttested": command.owner_attested,
        }
    )


def _calculation_id(*, action_id: object, evidence_digest: str, facts: object) -> str:
    return _canonical_digest(
        {
            "actionId": str(action_id),
            "evidenceDigest": evidence_digest,
            "facts": facts,
            "policyVersion": _POLICY_VERSION.value,
        }
    )


def _normalize_evidence(command):
    reference = command.evidence_reference.strip()
    if (
        not reference
        or len(reference) > 255
        or not isinstance(command.owner_attested, bool)
        or not isinstance(command.evidence_mode, InvestmentEvidenceMode)
        or not isinstance(command.document_status, InvestmentDocumentStatus)
    ):
        raise InvestmentsError.invalid_input()
    if command.evidence_mode is InvestmentEvidenceMode.LINKED_SOURCES:
        valid = (
            command.bank_transaction_id is not None
            and command.document_id is not None
            and command.document_status is InvestmentDocumentStatus.ATTACHED
            and not command.owner_attested
        )
    else:
        valid = (
            command.bank_transaction_id is None
            and command.document_id is None
            and command.document_status
            is InvestmentDocumentStatus.MISSING_ACCEPTED_WARNING
            and command.owner_attested
        )
    if not valid:
        raise InvestmentsError.invalid_input()
    normalized = replace(command, evidence_reference=reference)
    return normalized, _evidence_digest(normalized)


def _valid_basis_points(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 10_000
    )


def _purchase_classification_is_supported(
    *,
    kind: InvestmentKind,
    classification: InvestmentAccountingClassification,
    investment_key: str,
    org_number: str | None,
    fund_equity_ratio_basis_points: int | None,
    fund_tax_statement_reference: str | None,
) -> bool:
    if kind is InvestmentKind.NORWEGIAN_PRIVATE_COMPANY:
        return (
            classification in _PRIVATE_CLASSIFICATIONS
            and org_number is not None
            and re.fullmatch(r"[0-9]{9}", org_number) is not None
            and fund_equity_ratio_basis_points is None
            and fund_tax_statement_reference is None
        )
    if kind is InvestmentKind.NORWEGIAN_LISTED_SHARE:
        return (
            classification
            is InvestmentAccountingClassification.CURRENT_LISTED_SHARE
            and re.fullmatch(r"NO[A-Z0-9]{10}", investment_key) is not None
            and (org_number is None or re.fullmatch(r"[0-9]{9}", org_number) is not None)
            and fund_equity_ratio_basis_points is None
            and fund_tax_statement_reference is None
        )
    if kind is InvestmentKind.NORWEGIAN_EQUITY_FUND:
        return (
            classification is InvestmentAccountingClassification.CURRENT_FUND
            and re.fullmatch(r"NO[A-Z0-9]{10}", investment_key) is not None
            and org_number is None
            and _valid_basis_points(fund_equity_ratio_basis_points)
            and fund_tax_statement_reference is not None
            and 0 < len(fund_tax_statement_reference) <= 255
        )
    return False


def _sum_money(values: tuple[Money, ...]) -> Money:
    return Money.nok(sum((value.amount for value in values), Decimal("0")))


def _replacement_activity_kind(command) -> InvestmentActivityKind:
    if isinstance(command, RecordSharePurchaseCommand):
        return InvestmentActivityKind.SHARE_PURCHASE
    if isinstance(command, RecordShareSaleCommand):
        return InvestmentActivityKind.SHARE_SALE
    if isinstance(command, RecordReceivedDividendCommand):
        return InvestmentActivityKind.DIVIDEND_RECEIVED
    if isinstance(command, RecordReceivedFundDistributionCommand):
        return InvestmentActivityKind.FUND_DISTRIBUTION_RECEIVED
    raise InvestmentsError.invalid_input()


def _sale_calculations(
    *, command: RecordShareSaleCommand, facts, net_proceeds: Money
) -> tuple[
    tuple[InvestmentSaleLotCalculation, ...], Money, Money, Money, Money
]:
    lots = facts.lot_facts
    if (
        not lots
        or sum(lot.allocated_share_count for lot in lots) != command.sold_share_count
        or _sum_money(tuple(lot.allocated_book_cost_basis for lot in lots))
        != facts.fifo_book_cost_basis_reduction
        or _sum_money(tuple(lot.allocated_tax_basis for lot in lots))
        != facts.fifo_tax_basis_reduction
    ):
        raise InvestmentsError.unavailable()

    is_fund = facts.investment_kind is InvestmentKind.NORWEGIAN_EQUITY_FUND
    if is_fund:
        if (
            not _valid_basis_points(command.sale_year_fund_equity_ratio_basis_points)
            or command.fund_tax_statement_reference is None
            or not command.fund_tax_statement_reference.strip()
            or len(command.fund_tax_statement_reference.strip()) > 255
        ):
            raise InvestmentsError.invalid_input()
    elif (
        facts.investment_kind
        not in {
            InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
            InvestmentKind.NORWEGIAN_LISTED_SHARE,
        }
        or command.sale_year_fund_equity_ratio_basis_points is not None
        or command.fund_tax_statement_reference is not None
    ):
        raise InvestmentsError.invalid_input()

    calculations: list[InvestmentSaleLotCalculation] = []
    allocated_so_far = Money.nok("0")
    for index, lot in enumerate(lots):
        if lot.allocated_share_count <= 0:
            raise InvestmentsError.unavailable()
        if index == len(lots) - 1:
            allocated_proceeds = Money.nok(net_proceeds.amount - allocated_so_far.amount)
        else:
            allocated_proceeds = Money.nok(
                net_proceeds.amount
                * Decimal(lot.allocated_share_count)
                / Decimal(command.sold_share_count)
            )
            allocated_so_far = Money.nok(
                allocated_so_far.amount + allocated_proceeds.amount
            )
        tax_result = Money.nok(
            allocated_proceeds.amount - lot.allocated_tax_basis.amount
        )
        average_ratio: Decimal | None = None
        exempt_gain = _ZERO
        taxable_gain = _ZERO
        non_deductible_loss = _ZERO
        deductible_loss = _ZERO
        if is_fund:
            if not _valid_basis_points(
                lot.acquisition_year_fund_equity_ratio_basis_points
            ):
                raise InvestmentsError.unavailable()
            average_ratio = (
                Decimal(lot.acquisition_year_fund_equity_ratio_basis_points)
                + Decimal(command.sale_year_fund_equity_ratio_basis_points)
            ) / Decimal("2")
            equity_part = Money.nok(
                abs(tax_result.amount) * average_ratio / Decimal("10000")
            )
            ordinary_part = Money.nok(abs(tax_result.amount) - equity_part.amount)
            if tax_result.amount >= 0:
                exempt_gain, taxable_gain = equity_part, ordinary_part
            else:
                non_deductible_loss, deductible_loss = equity_part, ordinary_part
        elif tax_result.amount >= 0:
            exempt_gain = tax_result
        else:
            non_deductible_loss = Money.nok(-tax_result.amount)
        calculations.append(
            InvestmentSaleLotCalculation(
                lot_id=lot.lot_id,
                allocation_order=lot.allocation_order,
                allocated_share_count=lot.allocated_share_count,
                allocated_net_proceeds=allocated_proceeds,
                allocated_book_cost_basis=lot.allocated_book_cost_basis,
                allocated_tax_basis=lot.allocated_tax_basis,
                tax_gain_or_loss=tax_result,
                average_fund_equity_ratio_basis_points=average_ratio,
                exempt_gain=exempt_gain,
                taxable_gain=taxable_gain,
                non_deductible_loss=non_deductible_loss,
                deductible_loss=deductible_loss,
            )
        )
    result = tuple(calculations)
    return (
        result,
        _sum_money(tuple(item.exempt_gain for item in result)),
        _sum_money(tuple(item.taxable_gain for item in result)),
        _sum_money(tuple(item.non_deductible_loss for item in result)),
        _sum_money(tuple(item.deductible_loss for item in result)),
    )


class InvestmentsService:
    def __init__(self, persistence: InvestmentsPersistence) -> None:
        self._persistence = persistence

    async def get_investment_correction_replay(
        self, command: CorrectInvestmentCommand
    ) -> RecordedInvestmentCorrection | None:
        return await self._persistence.get_investment_correction_replay(command)

    async def prepare_investment_correction(
        self, command: CorrectInvestmentCommand
    ) -> PreparedInvestmentCorrection:
        replacement_kind = _replacement_activity_kind(command.replacement)
        replacement_action_id = command.replacement.action_id
        reason = command.reason.strip()
        replacement = command.replacement
        if (
            replacement_kind is not command.original_activity_kind
            or replacement.company_id != command.company_id
            or replacement.actor_id != command.actor_id
            or replacement.income_year != command.income_year
            or replacement.action_id == command.original_action_id
            or replacement.idempotency_key == command.idempotency_key
            or command.correction_date.value.year != command.income_year.value
            or not reason
            or len(reason) > 500
        ):
            raise InvestmentsError.invalid_input()
        normalized, evidence_digest = _normalize_evidence(
            replace(command, reason=reason)
        )
        prepared = await self._persistence.prepare_investment_correction(
            normalized,
            evidence_digest=evidence_digest,
        )
        if str(replacement_action_id) == str(normalized.original_action_id):
            raise InvestmentsError.invalid_input()
        return replace(prepared, evidence_digest=evidence_digest)

    async def complete_investment_correction(
        self,
        command: CorrectInvestmentCommand,
        *,
        prepared: PreparedInvestmentCorrection,
        replacement,
    ) -> RecordedInvestmentCorrection:
        normalized, _ = _normalize_evidence(replace(command, reason=command.reason.strip()))
        if replacement.position_id != prepared.original_position_id:
            raise InvestmentsError.unavailable()
        return await self._persistence.complete_investment_correction(
            normalized,
            prepared=prepared,
            replacement=replacement,
        )

    async def get_share_purchase_replay(self, command: RecordSharePurchaseCommand) -> RecordedSharePurchase | None:
        return await self._persistence.get_share_purchase_replay(command)

    async def get_share_sale_replay(self, command: RecordShareSaleCommand) -> RecordedShareSale | None:
        return await self._persistence.get_share_sale_replay(command)

    async def get_received_dividend_replay(self, command: RecordReceivedDividendCommand) -> RecordedReceivedDividend | None:
        return await self._persistence.get_received_dividend_replay(command)

    async def get_received_fund_distribution_replay(self, command: RecordReceivedFundDistributionCommand) -> RecordedReceivedFundDistribution | None:
        return await self._persistence.get_received_fund_distribution_replay(command)

    async def prepare_share_purchase(self, command: RecordSharePurchaseCommand) -> PreparedSharePurchase:
        investment_key = command.investment_key.strip()
        investment_name = command.investment_name.strip()
        org_number = command.org_number.strip() if command.org_number else None
        fund_reference = command.fund_tax_statement_reference.strip() if command.fund_tax_statement_reference else None
        if (
            not isinstance(command.share_count, int)
            or isinstance(command.share_count, bool)
            or command.share_count <= 0
            or command.purchase_amount.amount <= 0
            or command.transaction_costs.amount < 0
            or command.acquisition_date.value.year != command.income_year.value
            or not investment_key
            or len(investment_key) > 255
            or not investment_name
            or len(investment_name) > 255
            or not isinstance(command.investment_kind, InvestmentKind)
            or not isinstance(command.accounting_classification, InvestmentAccountingClassification)
            or command.tax_treatment is not InvestmentTaxTreatment.EXEMPTION_METHOD
            or not _purchase_classification_is_supported(
                kind=command.investment_kind,
                classification=command.accounting_classification,
                investment_key=investment_key,
                org_number=org_number,
                fund_equity_ratio_basis_points=command.fund_equity_ratio_basis_points,
                fund_tax_statement_reference=fund_reference,
            )
        ):
            raise InvestmentsError.invalid_input()
        normalized, evidence_digest = _normalize_evidence(
            replace(command, investment_key=investment_key, investment_name=investment_name, org_number=org_number, fund_tax_statement_reference=fund_reference)
        )
        capitalized_cost = Money.nok(normalized.purchase_amount.amount + normalized.transaction_costs.amount)
        calculation_id = _calculation_id(
            action_id=normalized.action_id,
            evidence_digest=evidence_digest,
            facts={"bookCost": format(capitalized_cost.amount, "f"), "taxBasis": format(capitalized_cost.amount, "f")},
        )
        prepared = await self._persistence.prepare_share_purchase(
            normalized,
            capitalized_cost=capitalized_cost,
            evidence_digest=evidence_digest,
            calculation_id=calculation_id,
        )
        return replace(prepared, investment_name=normalized.investment_name, accounting_classification=normalized.accounting_classification, purchase_amount=capitalized_cost, evidence_digest=evidence_digest, calculation_id=calculation_id)

    async def complete_share_purchase(self, command: RecordSharePurchaseCommand, *, prepared: PreparedSharePurchase, accounting_entry_id: AccountingEntryReference) -> RecordedSharePurchase:
        normalized, _ = _normalize_evidence(replace(
            command,
            investment_key=command.investment_key.strip(),
            investment_name=command.investment_name.strip(),
            org_number=command.org_number.strip() if command.org_number else None,
            fund_tax_statement_reference=command.fund_tax_statement_reference.strip() if command.fund_tax_statement_reference else None,
        ))
        return await self._persistence.complete_share_purchase(normalized, prepared=prepared, accounting_entry_id=accounting_entry_id)

    async def prepare_share_sale(self, command: RecordShareSaleCommand) -> PreparedShareSale:
        if (
            not isinstance(command.sold_share_count, int)
            or isinstance(command.sold_share_count, bool)
            or command.sold_share_count <= 0
            or command.proceeds.amount <= 0
            or command.transaction_costs.amount < 0
            or command.transaction_costs.amount >= command.proceeds.amount
            or command.sale_date.value.year != command.income_year.value
        ):
            raise InvestmentsError.invalid_input()
        normalized, evidence_digest = _normalize_evidence(replace(
            command,
            fund_tax_statement_reference=command.fund_tax_statement_reference.strip() if command.fund_tax_statement_reference else None,
        ))
        net_proceeds = Money.nok(normalized.proceeds.amount - normalized.transaction_costs.amount)
        facts = await self._persistence.prepare_share_sale(normalized, net_proceeds=net_proceeds, evidence_digest=evidence_digest)
        calculations, exempt, taxable, non_deductible, deductible = _sale_calculations(command=normalized, facts=facts, net_proceeds=net_proceeds)
        book_result = Money.nok(net_proceeds.amount - facts.fifo_book_cost_basis_reduction.amount)
        tax_result = Money.nok(net_proceeds.amount - facts.fifo_tax_basis_reduction.amount)
        calculation_id = _calculation_id(
            action_id=normalized.action_id,
            evidence_digest=evidence_digest,
            facts={
                "bookGainOrLoss": format(book_result.amount, "f"),
                "deductibleLoss": format(deductible.amount, "f"),
                "exemptGain": format(exempt.amount, "f"),
                "nonDeductibleLoss": format(non_deductible.amount, "f"),
                "taxGainOrLoss": format(tax_result.amount, "f"),
                "taxableGain": format(taxable.amount, "f"),
            },
        )
        return PreparedShareSale(
            position_id=facts.position_id,
            investment_name=facts.investment_name,
            accounting_classification=facts.accounting_classification,
            investment_kind=facts.investment_kind,
            net_proceeds=net_proceeds,
            fifo_cost_basis_reduction=facts.fifo_book_cost_basis_reduction,
            fifo_tax_basis_reduction=facts.fifo_tax_basis_reduction,
            book_gain_or_loss=book_result,
            tax_gain_or_loss=tax_result,
            exempt_gain=exempt,
            taxable_gain=taxable,
            non_deductible_loss=non_deductible,
            deductible_loss=deductible,
            lot_calculations=calculations,
            evidence_digest=evidence_digest,
            calculation_id=calculation_id,
        )

    async def complete_share_sale(self, command: RecordShareSaleCommand, *, prepared: PreparedShareSale, accounting_entry_id: AccountingEntryReference) -> RecordedShareSale:
        normalized, _ = _normalize_evidence(replace(
            command,
            fund_tax_statement_reference=command.fund_tax_statement_reference.strip() if command.fund_tax_statement_reference else None,
        ))
        return await self._persistence.complete_share_sale(normalized, prepared=prepared, accounting_entry_id=accounting_entry_id)

    async def prepare_received_dividend(self, command: RecordReceivedDividendCommand) -> PreparedReceivedDividend:
        paying_company_name = command.paying_company_name.strip()
        group_reference = command.group_evidence_reference.strip() if command.group_evidence_reference else None
        group_valid = isinstance(command.group_exception_claimed, bool) and (
            (
                command.group_exception_claimed
                and _valid_basis_points(command.year_end_ownership_basis_points)
                and _valid_basis_points(command.year_end_voting_basis_points)
                and command.year_end_ownership_basis_points > 9_000
                and command.year_end_voting_basis_points > 9_000
                and group_reference is not None
                and 0 < len(group_reference) <= 255
            )
            or (
                not command.group_exception_claimed
                and command.year_end_ownership_basis_points is None
                and command.year_end_voting_basis_points is None
                and group_reference is None
            )
        )
        if (
            not paying_company_name
            or len(paying_company_name) > 255
            or command.gross_amount.amount <= 0
            or command.declared_date.value.year != command.income_year.value
            or command.paid_date.value.year != command.income_year.value
            or command.declared_date.value > command.paid_date.value
            or command.tax_treatment is not InvestmentTaxTreatment.EXEMPTION_METHOD
            or command.lawful_dividend_confirmed is not True
            or not group_valid
        ):
            raise InvestmentsError.invalid_input()
        normalized, evidence_digest = _normalize_evidence(replace(command, paying_company_name=paying_company_name, group_evidence_reference=group_reference))
        facts = await self._persistence.prepare_received_dividend(normalized, evidence_digest=evidence_digest)
        if facts.investment_kind not in {InvestmentKind.NORWEGIAN_PRIVATE_COMPANY, InvestmentKind.NORWEGIAN_LISTED_SHARE}:
            raise InvestmentsError.invalid_input()
        taxable_add_back = _ZERO if normalized.group_exception_claimed else Money.nok(normalized.gross_amount.amount * Decimal("0.03"))
        calculation_id = _calculation_id(
            action_id=normalized.action_id,
            evidence_digest=evidence_digest,
            facts={"groupExceptionApplied": normalized.group_exception_claimed, "taxableAddBack": format(taxable_add_back.amount, "f")},
        )
        return PreparedReceivedDividend(
            position_id=facts.position_id,
            investment_name=facts.investment_name,
            paying_company_name=normalized.paying_company_name,
            taxable_add_back=taxable_add_back,
            group_exception_applied=normalized.group_exception_claimed,
            evidence_digest=evidence_digest,
            calculation_id=calculation_id,
        )

    async def complete_received_dividend(self, command: RecordReceivedDividendCommand, *, prepared: PreparedReceivedDividend, accounting_entry_id: AccountingEntryReference) -> RecordedReceivedDividend:
        normalized, _ = _normalize_evidence(replace(
            command,
            paying_company_name=prepared.paying_company_name,
            group_evidence_reference=command.group_evidence_reference.strip() if command.group_evidence_reference else None,
        ))
        return await self._persistence.complete_received_dividend(normalized, prepared=prepared, accounting_entry_id=accounting_entry_id)

    async def prepare_received_fund_distribution(self, command: RecordReceivedFundDistributionCommand) -> PreparedReceivedFundDistribution:
        fund_name = command.fund_name.strip()
        tax_reference = command.fund_tax_statement_reference.strip()
        if (
            not fund_name
            or len(fund_name) > 255
            or not tax_reference
            or len(tax_reference) > 255
            or command.gross_amount.amount <= 0
            or command.entitlement_date.value.year != command.income_year.value
            or command.paid_date.value.year != command.income_year.value
            or command.entitlement_date.value > command.paid_date.value
            or not _valid_basis_points(command.opening_fund_equity_ratio_basis_points)
        ):
            raise InvestmentsError.invalid_input()
        normalized, evidence_digest = _normalize_evidence(replace(command, fund_name=fund_name, fund_tax_statement_reference=tax_reference))
        facts = await self._persistence.prepare_received_fund_distribution(normalized, evidence_digest=evidence_digest)
        if facts.investment_kind is not InvestmentKind.NORWEGIAN_EQUITY_FUND:
            raise InvestmentsError.invalid_input()
        ratio = normalized.opening_fund_equity_ratio_basis_points
        if ratio > 8_000:
            dividend_portion = normalized.gross_amount
        elif ratio < 2_000:
            dividend_portion = _ZERO
        else:
            dividend_portion = Money.nok(normalized.gross_amount.amount * Decimal(ratio) / Decimal("10000"))
        interest_portion = Money.nok(normalized.gross_amount.amount - dividend_portion.amount)
        taxable_add_back = Money.nok(dividend_portion.amount * Decimal("0.03"))
        total_taxable_income = Money.nok(interest_portion.amount + taxable_add_back.amount)
        calculation_id = _calculation_id(
            action_id=normalized.action_id,
            evidence_digest=evidence_digest,
            facts={
                "dividendPortion": format(dividend_portion.amount, "f"),
                "interestPortion": format(interest_portion.amount, "f"),
                "taxableAddBack": format(taxable_add_back.amount, "f"),
                "totalTaxableIncome": format(total_taxable_income.amount, "f"),
            },
        )
        return PreparedReceivedFundDistribution(
            position_id=facts.position_id,
            investment_name=facts.investment_name,
            fund_name=normalized.fund_name,
            dividend_portion=dividend_portion,
            interest_portion=interest_portion,
            taxable_add_back=taxable_add_back,
            total_taxable_income=total_taxable_income,
            evidence_digest=evidence_digest,
            calculation_id=calculation_id,
        )

    async def complete_received_fund_distribution(self, command: RecordReceivedFundDistributionCommand, *, prepared: PreparedReceivedFundDistribution, accounting_entry_id: AccountingEntryReference) -> RecordedReceivedFundDistribution:
        normalized, _ = _normalize_evidence(replace(command, fund_name=prepared.fund_name, fund_tax_statement_reference=command.fund_tax_statement_reference.strip()))
        return await self._persistence.complete_received_fund_distribution(normalized, prepared=prepared, accounting_entry_id=accounting_entry_id)


__all__ = ["InvestmentsService"]
