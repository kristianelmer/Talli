"""Deterministic corporate-governance policy."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from talli_backend.modules.corporate_governance.public import (
    SHA256_PATTERN,
    AnnualCloseProposalCommand,
    AnnualDataSourceFacts,
    ApprovedAnnualBasis,
    BoardMeeting,
    CanonicalAnnualCloseDecision,
    CanonicalBoardParticipant,
    CanonicalDecisionShareholder,
    CanonicalOwnerDividendDecision,
    CanonicalShareholderLoan,
    CorporateAccountMovementFacts,
    CorporateArtifactKind,
    CorporateArtifactVariant,
    CorporateDecisionFactSources,
    CorporateDecisionKind,
    CorporateDocumentReadiness,
    CorporateDocumentReadinessBlocker,
    CorporateGovernanceError,
    CorporateGovernanceErrorCode,
    CorporateLifecycleSnapshot,
    CorporateReadinessSource,
    DerivedCorporateDecisionFacts,
    GeneralMeeting,
    OwnerDividendAllocation,
    OwnerDividendConfirmations,
    OwnerDividendFacts,
    OwnerDividendFinancialTotals,
    OwnerDividendProposalCommand,
    OwnerDividendState,
    PersistedShareholderFacts,
    RecordShareholderLoanCommand,
    RenderedCorporateArtifact,
    ReviewedOwnerDividendFacts,
    ReviewedShareholderFacts,
    ShareholderLoanDirection,
    ShareholderLoanDocumentStatus,
    ShareholderVote,
)
from talli_backend.modules.corporate_governance.rendering import (
    render_corporate_documents,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear

_ORG_NUMBER = re.compile(r"^[0-9]{9}$")
_TEMPLATE_FAMILY = "norwegian_simple_as"
_TEMPLATE_VERSION = "corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1"


def _fail(code: CorporateGovernanceErrorCode, message: str) -> None:
    raise CorporateGovernanceError.invalid(code, message)


def _text(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFC", value).strip().split())
    if not normalized:
        _fail(
            CorporateGovernanceErrorCode.INVALID_INPUT,
            "Persisted corporate facts contain an empty value.",
        )
    return normalized


def _safe_integer(
    value: int,
    *,
    minimum: int = 0,
    code: CorporateGovernanceErrorCode = CorporateGovernanceErrorCode.INVALID_INPUT,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail(code, "Corporate decision requires an exact supported integer.")
    return value


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "value") and value.__class__.__module__.startswith("talli_backend"):
        inner = value.value
        if hasattr(inner, "isoformat"):
            return inner.isoformat()
        return inner
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        _json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _basis_source_hash(
    basis: ApprovedAnnualBasis | CorporateReadinessSource,
) -> str:
    if not SHA256_PATTERN.fullmatch(basis.annual_data_sha256) or not SHA256_PATTERN.fullmatch(
        basis.governance_basis_sha256
    ):
        _fail(
            CorporateGovernanceErrorCode.INVALID_INPUT,
            "Annual basis requires exact SHA-256 identities.",
        )
    return _sha256(
        _canonical_json(
            {
                "governance_basis_hash": basis.governance_basis_sha256,
                "annual_close_source_id": str(basis.source_id),
                "annual_data_hash": basis.annual_data_sha256,
            }
        )
    )


def _ledger_account_balance_ore(
    lines: tuple[CorporateAccountMovementFacts, ...],
    account: str,
    income_year: IncomeYear,
) -> int:
    return sum(
        line.debit_ore - line.credit_ore
        for line in lines
        if line.income_year == income_year and line.account == account
    )


def _project_governance_annual_basis(
    source: AnnualDataSourceFacts,
    ledger_lines: tuple[CorporateAccountMovementFacts, ...],
) -> ApprovedAnnualBasis:
    """Project only the source facts required by corporate decisions.

    This reproduces the predecessor corporate-governance basis. It deliberately
    contains no annual-accounts filing identifiers, fields, or readiness rules.
    """

    def account_balance(account: str) -> int:
        return _ledger_account_balance_ore(
            ledger_lines, account, source.income_year
        )

    def account_credit(account: str) -> int:
        return -account_balance(account)

    def debit_total(accounts: set[str]) -> int:
        return sum(
            line.debit_ore
            for line in ledger_lines
            if line.income_year == source.income_year
            and line.account in accounts
        )

    cash_ore = account_balance("1920")
    financial_income_ore = sum(
        account_credit(account)
        for account in ("8070", "8071", "8074", "8050")
    )
    administration_costs_ore = debit_total(
        {"7770", "6700", "6705", "6420", "7790", "6720", "7795"}
    )
    financial_costs_ore = debit_total({"8090", "8171", "8174"})
    tax_expense_ore = account_balance("8300")
    share_capital_ore = account_credit("2000")
    retained_earnings_ore = account_credit("2050")
    result_after_tax_ore = (
        financial_income_ore
        - administration_costs_ore
        - financial_costs_ore
        - tax_expense_ore
    )
    available_distribution_ore = max(
        0, retained_earnings_ore + result_after_tax_ore
    )
    equity_ore = (
        share_capital_ore
        + retained_earnings_ore
        + result_after_tax_ore
    )
    if equity_ore < 0 or cash_ore < 0:
        _fail(
            CorporateGovernanceErrorCode.UNSUPPORTED_DIVIDEND_BASIS,
            "Negative equity or liquidity is outside the supported path.",
        )

    annual_snapshot = {
        "id": str(source.source_id),
        "company_id": str(source.company_id),
        "income_year": int(source.income_year),
        "answers": source.answers,
        "confirmations": source.confirmations,
        "no_activity_confirmed": source.no_activity_confirmed,
        "annual_full_time_equivalents": source.annual_full_time_equivalents,
        "completed_at": source.completed_at,
        "updated_at": source.updated_at,
    }
    annual_data_sha256 = _sha256(_canonical_json(annual_snapshot))
    governance_basis = {
        "policy_version": "corporate-governance-basis-v1",
        "source_id": str(source.source_id),
        "income_year": int(source.income_year),
        "annual_data_sha256": annual_data_sha256,
        "result_after_tax_ore": result_after_tax_ore,
        "equity_ore": equity_ore,
        "available_distribution_ore": available_distribution_ore,
        "cash_ore": cash_ore,
    }
    return ApprovedAnnualBasis(
        source_id=source.source_id,
        income_year=source.income_year,
        latest_approved=True,
        annual_data_sha256=annual_data_sha256,
        governance_basis_sha256=_sha256(
            _canonical_json(governance_basis)
        ),
        result_after_tax_ore=result_after_tax_ore,
        equity_ore=equity_ore,
        available_distribution_ore=available_distribution_ore,
        cash_ore=cash_ore,
    )


def _source_hash(
    command: OwnerDividendProposalCommand | AnnualCloseProposalCommand,
) -> str:
    return _basis_source_hash(command.annual_basis)


def canonical_owner_dividend_payload(
    decision: CanonicalOwnerDividendDecision,
) -> dict[str, Any]:
    return {
        "request_id": str(decision.decision_id),
        "company_id": str(decision.company_id),
        "organization_number": decision.organization_number,
        "legal_name": decision.legal_name,
        "income_year": int(decision.income_year),
        "decision_kind": "owner_dividend",
        "annual_close_source_id": str(decision.annual_close_source_id),
        "source_hash": decision.source_hash,
        "template_family": decision.template_family,
        "template_version": decision.template_version,
        "annual_basis_year": int(decision.annual_basis_year),
        "financial_totals": {
            "result_after_tax_ore": decision.financial_totals.result_after_tax_ore,
            "equity_ore": decision.financial_totals.equity_ore,
            "available_distribution_ore": decision.financial_totals.available_distribution_ore,
            "cash_ore": decision.financial_totals.cash_ore,
        },
        "board_meeting": {
            "meeting_date": decision.board_meeting.meeting_date.value.isoformat(),
            "meeting_time": decision.board_meeting.meeting_time.isoformat(),
            "place": decision.board_meeting.place,
            "treatment_method": decision.board_meeting.treatment_method.value,
        },
        "board_participants": [
            {
                "participant_id": participant.participant_id,
                "name": participant.name,
                "role": participant.role.value,
            }
            for participant in decision.board_participants
        ],
        "general_meeting": {
            "meeting_date": decision.general_meeting.meeting_date.value.isoformat(),
            "meeting_time": decision.general_meeting.meeting_time.isoformat(),
            "place": decision.general_meeting.place,
            "meeting_form": decision.general_meeting.meeting_form.value,
            "chair_name": decision.general_meeting.chair_name,
            "co_signer_name": decision.general_meeting.co_signer_name,
        },
        "shareholders": [
            {
                "shareholder_id": shareholder.shareholder_id,
                "name": shareholder.name,
                "share_count": shareholder.share_count,
                "represented_share_count": shareholder.represented_share_count,
                "vote": shareholder.vote.value,
            }
            for shareholder in decision.shareholders
        ],
        "total_company_shares": decision.total_company_shares,
        "one_share_class_confirmed": decision.one_share_class_confirmed,
        "dividend": {
            "amount_ore": decision.dividend.amount_ore,
            "payment_date": decision.dividend.payment_date.value.isoformat(),
            "liquidity_after_payment_ore": decision.dividend.liquidity_after_payment_ore,
            "allocations": [
                {
                    "shareholder_id": allocation.shareholder_id,
                    "amount_ore": allocation.amount_ore,
                }
                for allocation in decision.dividend.allocations
            ],
        },
        "annual_result_allocation_ore": decision.annual_result_allocation_ore,
        "confirmations": {
            "latest_approved_annual_accounts": decision.confirmations.latest_approved_annual_accounts,
            "supported_dividend_basis": decision.confirmations.supported_dividend_basis,
            "full_board_participation": decision.confirmations.full_board_participation,
            "full_share_representation": decision.confirmations.full_share_representation,
            "unanimous_board": decision.confirmations.unanimous_board,
            "unanimous_shareholders": decision.confirmations.unanimous_shareholders,
            "proportional_allocation": decision.confirmations.proportional_allocation,
            "prudent_equity_and_liquidity": decision.confirmations.prudent_equity_and_liquidity,
        },
    }


def canonical_annual_close_payload(
    decision: CanonicalAnnualCloseDecision,
) -> dict[str, Any]:
    return {
        "request_id": str(decision.decision_id),
        "company_id": str(decision.company_id),
        "organization_number": decision.organization_number,
        "legal_name": decision.legal_name,
        "income_year": int(decision.income_year),
        "decision_kind": "annual_close",
        "annual_close_source_id": str(decision.annual_close_source_id),
        "source_hash": decision.source_hash,
        "template_family": decision.template_family,
        "template_version": decision.template_version,
        "annual_basis_year": int(decision.annual_basis_year),
        "financial_totals": {
            "result_after_tax_ore": decision.financial_totals.result_after_tax_ore,
            "equity_ore": decision.financial_totals.equity_ore,
            "available_distribution_ore": decision.financial_totals.available_distribution_ore,
            "cash_ore": decision.financial_totals.cash_ore,
        },
        "board_meeting": {
            "meeting_date": decision.board_meeting.meeting_date.value.isoformat(),
            "meeting_time": decision.board_meeting.meeting_time.isoformat(),
            "place": decision.board_meeting.place,
            "treatment_method": decision.board_meeting.treatment_method.value,
        },
        "board_participants": [
            {
                "participant_id": participant.participant_id,
                "name": participant.name,
                "role": participant.role.value,
            }
            for participant in decision.board_participants
        ],
        "general_meeting": {
            "meeting_date": decision.general_meeting.meeting_date.value.isoformat(),
            "meeting_time": decision.general_meeting.meeting_time.isoformat(),
            "place": decision.general_meeting.place,
            "meeting_form": decision.general_meeting.meeting_form.value,
            "chair_name": decision.general_meeting.chair_name,
            "co_signer_name": decision.general_meeting.co_signer_name,
        },
        "shareholders": [
            {
                "shareholder_id": shareholder.shareholder_id,
                "name": shareholder.name,
                "share_count": shareholder.share_count,
                "represented_share_count": shareholder.represented_share_count,
                "vote": shareholder.vote.value,
            }
            for shareholder in decision.shareholders
        ],
        "total_company_shares": decision.total_company_shares,
        "one_share_class_confirmed": decision.one_share_class_confirmed,
        "dividend": None,
        "annual_result_allocation_ore": decision.annual_result_allocation_ore,
        "confirmations": {
            "latest_approved_annual_accounts": decision.confirmations.latest_approved_annual_accounts,
            "supported_dividend_basis": decision.confirmations.supported_dividend_basis,
            "full_board_participation": decision.confirmations.full_board_participation,
            "full_share_representation": decision.confirmations.full_share_representation,
            "unanimous_board": decision.confirmations.unanimous_board,
            "unanimous_shareholders": decision.confirmations.unanimous_shareholders,
            "proportional_allocation": decision.confirmations.proportional_allocation,
            "prudent_equity_and_liquidity": decision.confirmations.prudent_equity_and_liquidity,
        },
    }


@dataclass(frozen=True, slots=True)
class _PreparedDecisionFacts:
    organization_number: str
    legal_name: str
    basis: ApprovedAnnualBasis
    source_hash: str
    shareholders: tuple[PersistedShareholderFacts, ...]
    total_company_shares: int
    board_meeting: BoardMeeting
    board_participants: tuple[CanonicalBoardParticipant, ...]
    general_meeting: GeneralMeeting
    decision_shareholders: tuple[CanonicalDecisionShareholder, ...]
    full_representation: bool
    unanimous_shareholders: bool


def _prepare_decision_facts(
    command: AnnualCloseProposalCommand | OwnerDividendProposalCommand,
) -> _PreparedDecisionFacts:
    if command.company.company_id != command.company_id:
        _fail(
            CorporateGovernanceErrorCode.INVALID_INPUT,
            "Company identity does not match the decision scope.",
        )
    organization_number = _text(command.company.organization_number)
    legal_name = _text(command.company.legal_name)
    if not _ORG_NUMBER.fullmatch(organization_number):
        _fail(
            CorporateGovernanceErrorCode.INVALID_INPUT,
            "Organization number is invalid.",
        )

    basis = command.annual_basis
    if not basis.latest_approved:
        _fail(
            CorporateGovernanceErrorCode.LATEST_ANNUAL_ACCOUNTS_REQUIRED,
            "The latest approved annual accounts are required.",
        )
    _safe_integer(int(basis.income_year), minimum=2000)
    _safe_integer(basis.result_after_tax_ore, minimum=-(2**53 - 1))
    _safe_integer(basis.equity_ore)
    _safe_integer(basis.available_distribution_ore)
    _safe_integer(basis.cash_ore)

    shareholders = tuple(sorted(
        (
            replace(
                shareholder,
                shareholder_id=_text(shareholder.shareholder_id),
                name=_text(shareholder.name),
            )
            for shareholder in command.shareholders
        ),
        key=lambda shareholder: (shareholder.order, shareholder.shareholder_id),
    ))
    if not shareholders or len(
        {item.shareholder_id for item in shareholders}
    ) != len(shareholders):
        _fail(
            CorporateGovernanceErrorCode.INVALID_INPUT,
            "Shareholder facts are missing or duplicated.",
        )
    for shareholder in shareholders:
        _safe_integer(shareholder.share_count, minimum=1)
        _safe_integer(shareholder.order)
    total_company_shares = sum(item.share_count for item in shareholders)
    _safe_integer(total_company_shares, minimum=1)

    reviewed = command.reviewed_facts
    reviewed_shareholders = sorted(
        (
            (_text(item.shareholder_id), _text(item.name), item.share_count)
            for item in reviewed.shareholders
        ),
        key=lambda item: item[0],
    )
    expected_reviewed = sorted(
        (
            (item.shareholder_id, item.name, item.share_count)
            for item in shareholders
        ),
        key=lambda item: item[0],
    )
    if (
        reviewed.organization_number != organization_number
        or _text(reviewed.legal_name) != legal_name
        or reviewed_shareholders != expected_reviewed
        or reviewed.total_company_shares != total_company_shares
        or reviewed.available_distribution_ore
        != basis.available_distribution_ore
        or reviewed.annual_data_sha256 != basis.annual_data_sha256
        or reviewed.governance_basis_sha256 != basis.governance_basis_sha256
    ):
        _fail(
            CorporateGovernanceErrorCode.REVIEWED_FACTS_CHANGED,
            "Reviewed facts changed before the decision was submitted.",
        )

    participants = tuple(sorted(
        (
            replace(
                participant,
                participant_id=_text(participant.participant_id),
                name=_text(participant.name),
            )
            for participant in command.board_participants
        ),
        key=lambda participant: (participant.order, participant.participant_id),
    ))
    if not participants or len(
        {item.participant_id for item in participants}
    ) != len(participants):
        _fail(
            CorporateGovernanceErrorCode.INVALID_MEETING_FACTS,
            "Board participants are missing or duplicated.",
        )
    for participant in participants:
        _safe_integer(
            participant.order,
            code=CorporateGovernanceErrorCode.INVALID_MEETING_FACTS,
        )

    ballots: dict[str, Any] = {}
    for ballot in command.shareholder_ballots:
        shareholder_id = _text(ballot.shareholder_id)
        if shareholder_id in ballots:
            _fail(
                CorporateGovernanceErrorCode.SHAREHOLDER_FACTS_MISMATCH,
                "Shareholder ballot facts are duplicated.",
            )
        ballots[shareholder_id] = ballot
    if len(ballots) != len(shareholders):
        _fail(
            CorporateGovernanceErrorCode.SHAREHOLDER_FACTS_MISMATCH,
            "Every persisted shareholder must have one ballot.",
        )
    decision_shareholders: list[CanonicalDecisionShareholder] = []
    for shareholder in shareholders:
        ballot = ballots.get(shareholder.shareholder_id)
        if ballot is None:
            _fail(
                CorporateGovernanceErrorCode.SHAREHOLDER_FACTS_MISMATCH,
                "Every persisted shareholder must have one ballot.",
            )
        _safe_integer(
            ballot.represented_share_count,
            code=CorporateGovernanceErrorCode.SHAREHOLDER_FACTS_MISMATCH,
        )
        decision_shareholders.append(
            CanonicalDecisionShareholder(
                shareholder.shareholder_id,
                shareholder.name,
                shareholder.share_count,
                ballot.represented_share_count,
                ballot.vote,
            )
        )

    board_meeting = replace(
        command.board_meeting,
        place=_text(command.board_meeting.place),
    )
    general_meeting = replace(
        command.general_meeting,
        place=_text(command.general_meeting.place),
        chair_name=_text(command.general_meeting.chair_name),
        co_signer_name=_text(command.general_meeting.co_signer_name),
    )
    if general_meeting.meeting_date.value < board_meeting.meeting_date.value:
        _fail(
            CorporateGovernanceErrorCode.UNSUPPORTED_DIVIDEND_BASIS,
            "The general meeting cannot precede the board treatment.",
        )
    if (
        not command.one_share_class_confirmed
        or not command.supported_dividend_basis_confirmed
    ):
        _fail(
            CorporateGovernanceErrorCode.UNSUPPORTED_DIVIDEND_BASIS,
            "The decision basis is outside the supported path.",
        )
    if not command.full_board_participation_confirmed:
        _fail(
            CorporateGovernanceErrorCode.INCOMPLETE_BOARD,
            "Every board member must participate.",
        )
    full_representation = all(
        shareholder.represented_share_count == shareholder.share_count
        for shareholder in decision_shareholders
    )
    if not full_representation:
        _fail(
            CorporateGovernanceErrorCode.INCOMPLETE_SHARE_REPRESENTATION,
            "Every share must be represented.",
        )
    unanimous_shareholders = all(
        shareholder.vote == ShareholderVote.FOR
        for shareholder in decision_shareholders
    )
    if not command.unanimous_board_confirmed or not unanimous_shareholders:
        _fail(
            CorporateGovernanceErrorCode.NON_UNANIMOUS,
            "Only unanimous decisions are supported.",
        )

    return _PreparedDecisionFacts(
        organization_number=organization_number,
        legal_name=legal_name,
        basis=basis,
        source_hash=_source_hash(command),
        shareholders=shareholders,
        total_company_shares=total_company_shares,
        board_meeting=board_meeting,
        board_participants=tuple(
            CanonicalBoardParticipant(
                participant.participant_id,
                participant.name,
                participant.role,
            )
            for participant in participants
        ),
        general_meeting=general_meeting,
        decision_shareholders=tuple(decision_shareholders),
        full_representation=full_representation,
        unanimous_shareholders=unanimous_shareholders,
    )


class CorporateGovernanceService:
    def canonical_payload(
        self,
        decision: CanonicalOwnerDividendDecision | CanonicalAnnualCloseDecision,
    ) -> Mapping[str, object]:
        if isinstance(decision, CanonicalAnnualCloseDecision):
            return canonical_annual_close_payload(decision)
        return canonical_owner_dividend_payload(decision)

    def derive_decision_facts(
        self,
        *,
        sources: CorporateDecisionFactSources,
        ledger_lines: tuple[CorporateAccountMovementFacts, ...],
        decision_kind: CorporateDecisionKind,
        income_year: IncomeYear,
    ) -> DerivedCorporateDecisionFacts:
        candidates = [
            item
            for item in sources.annual_data
            if item.company_id == sources.company.company_id
            and (
                item.income_year == income_year
                if decision_kind is CorporateDecisionKind.ANNUAL_CLOSE
                else int(item.income_year) <= int(income_year)
            )
            and item.answers.get("general_meeting_approved") is True
        ]
        if not candidates:
            _fail(
                CorporateGovernanceErrorCode.LATEST_ANNUAL_ACCOUNTS_REQUIRED,
                "The latest approved annual accounts are required.",
            )
        source = max(candidates, key=lambda item: int(item.income_year))
        basis = _project_governance_annual_basis(source, ledger_lines)
        shareholders = sorted(
            sources.shareholders,
            key=lambda item: (item.order, item.shareholder_id),
        )
        if not shareholders:
            _fail(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                "Shareholder facts are missing.",
            )
        reviewed = ReviewedOwnerDividendFacts(
            organization_number=_text(sources.company.organization_number),
            legal_name=_text(sources.company.legal_name),
            shareholders=tuple(
                ReviewedShareholderFacts(
                    shareholder_id=_text(item.shareholder_id),
                    name=_text(item.name),
                    share_count=_safe_integer(item.share_count, minimum=1),
                )
                for item in shareholders
            ),
            total_company_shares=sum(item.share_count for item in shareholders),
            available_distribution_ore=basis.available_distribution_ore,
            annual_data_sha256=basis.annual_data_sha256,
            governance_basis_sha256=basis.governance_basis_sha256,
        )
        return DerivedCorporateDecisionFacts(
            sources.company,
            tuple(shareholders),
            basis,
            reviewed,
        )

    def source_hash(self, source: CorporateReadinessSource) -> str:
        return _basis_source_hash(source)

    def current_facts_match(
        self,
        decision: CorporateDecisionRecord,
        facts: DerivedCorporateDecisionFacts,
    ) -> bool:
        """Compare every mutable source fact persisted into a decision."""

        canonical = decision.canonical_input

        def value(camel: str, snake: str) -> object:
            return canonical.get(camel, canonical.get(snake))

        financial = value("financialTotals", "financial_totals")
        shareholders = canonical.get("shareholders")
        if not isinstance(financial, Mapping) or not isinstance(
            shareholders, (list, tuple)
        ):
            return False

        def nested(mapping: Mapping[str, object], camel: str, snake: str) -> object:
            return mapping.get(camel, mapping.get(snake))

        persisted_shareholders: list[tuple[str, str, int]] = []
        for shareholder in shareholders:
            if not isinstance(shareholder, Mapping):
                return False
            shareholder_id = nested(shareholder, "shareholderId", "shareholder_id")
            name = shareholder.get("name")
            share_count = nested(shareholder, "shareCount", "share_count")
            if (
                not isinstance(shareholder_id, str)
                or not isinstance(name, str)
                or isinstance(share_count, bool)
                or not isinstance(share_count, int)
            ):
                return False
            persisted_shareholders.append((shareholder_id, name, share_count))

        current_source = CorporateReadinessSource(
            source_id=facts.annual_basis.source_id,
            annual_data_sha256=facts.annual_basis.annual_data_sha256,
            governance_basis_sha256=(
                facts.annual_basis.governance_basis_sha256
            ),
        )
        return (
            str(value("annualCloseSourceId", "annual_close_source_id"))
            == str(facts.annual_basis.source_id)
            and (
                not decision.source_hash_uses_current_basis
                or decision.source_hash == self.source_hash(current_source)
            )
            and value("organizationNumber", "organization_number")
            == facts.company.organization_number
            and value("legalName", "legal_name") == facts.company.legal_name
            and value("annualBasisYear", "annual_basis_year")
            == int(facts.annual_basis.income_year)
            and nested(financial, "resultAfterTaxOre", "result_after_tax_ore")
            == facts.annual_basis.result_after_tax_ore
            and nested(financial, "equityOre", "equity_ore")
            == facts.annual_basis.equity_ore
            and nested(
                financial,
                "availableDistributionOre",
                "available_distribution_ore",
            )
            == facts.annual_basis.available_distribution_ore
            and nested(financial, "cashOre", "cash_ore")
            == facts.annual_basis.cash_ore
            and tuple(persisted_shareholders)
            == tuple(
                (item.shareholder_id, item.name, item.share_count)
                for item in facts.shareholders
            )
            and value("totalCompanyShares", "total_company_shares")
            == sum(item.share_count for item in facts.shareholders)
        )

    def assess_lifecycle(
        self,
        snapshot: CorporateLifecycleSnapshot,
        *,
        company_id: CompanyId,
        income_year: IncomeYear,
        decision_kind: CorporateDecisionKind,
        current_source_hash: str | None = None,
        current_facts_match: bool | None = None,
    ) -> CorporateDocumentReadiness:
        """Derive lifecycle, signer, payable, and readiness policy in Python."""

        required_kinds = (
            (
                CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL,
                CorporateArtifactKind.DIVIDEND_GENERAL_MEETING_MINUTES,
            )
            if decision_kind is CorporateDecisionKind.OWNER_DIVIDEND
            else (
                CorporateArtifactKind.ANNUAL_BOARD_MINUTES,
                CorporateArtifactKind.ANNUAL_GENERAL_MEETING_MINUTES,
            )
        )
        decision = next(
            (
                item
                for item in snapshot.decisions
                if item.company_id == company_id
                and item.income_year == income_year
                and item.decision_kind is decision_kind
            ),
            None,
        )
        missing = CorporateDocumentReadinessBlocker(
            "corporate_documents_decision_missing",
            (
                "Årsbeslutning med dokumentsett må opprettes."
                if decision_kind is CorporateDecisionKind.ANNUAL_CLOSE
                else "Utbyttebeslutning med dokumentsett må opprettes."
            ),
        )
        if decision is None:
            return CorporateDocumentReadiness(
                company_id=company_id,
                income_year=income_year,
                decision_kind=decision_kind,
                decision_id=None,
                document_set_id=None,
                decision_hash=None,
                source_hash=None,
                current_source_hash=current_source_hash,
                state=None,
                current_source_matches=(
                    False if current_source_hash is not None else None
                ),
                ready_for_signing=False,
                finalized=False,
                annual_submission_ready=False,
                generated_artifact_hashes={},
                signed_artifact_hashes={},
                required_signers={},
                declared_amount_ore=None,
                paid_amount_ore=None,
                remaining_amount_ore=None,
                finalization_id=None,
                accounting_policy_version=None,
                blockers=(missing,),
            )

        document_set = next(
            (
                item
                for item in snapshot.document_sets
                if item.document_set_id == decision.document_set_id
                and item.decision_id == decision.decision_id
                and item.decision_hash == decision.decision_hash
            ),
            None,
        )
        artifacts = tuple(
            item
            for item in snapshot.artifacts
            if document_set is not None
            and item.document_set_id == document_set.document_set_id
        )
        generated = {
            item.artifact_kind.value: item.content_sha256
            for item in artifacts
            if item.variant is CorporateArtifactVariant.UNSIGNED
        }
        signed = {
            item.artifact_kind.value: item.content_sha256
            for item in artifacts
            if item.variant is CorporateArtifactVariant.SIGNED_OWNER_ATTESTED
        }
        expected = {item.value for item in required_kinds}
        generated_complete = set(generated) == expected
        signed_complete = set(signed) == expected
        events = tuple(
            item
            for item in snapshot.events
            if item.decision_id == decision.decision_id
            and document_set is not None
            and item.document_set_id == document_set.document_set_id
            and item.decision_hash == decision.decision_hash
        )
        event_kinds = {item.event_kind for item in events}
        finalization = next(
            (
                item
                for item in snapshot.finalizations
                if item.decision_id == decision.decision_id
                and item.decision_hash == decision.decision_hash
            ),
            None,
        )
        current_hash_matches = (
            None
            if current_source_hash is None
            else decision.source_hash == current_source_hash
        )
        current_source_matches = (
            False
            if current_hash_matches is False or current_facts_match is False
            else current_hash_matches
        )

        canonical = decision.canonical_input
        board_participants = canonical.get("boardParticipants")
        if board_participants is None:
            board_participants = canonical.get("board_participants")
        general_meeting = canonical.get("generalMeeting")
        if general_meeting is None:
            general_meeting = canonical.get("general_meeting")
        if not isinstance(board_participants, (list, tuple)) or not isinstance(
            general_meeting, Mapping
        ):
            raise CorporateGovernanceError.unavailable()

        def signer_names(values: list[object]) -> tuple[str, ...]:
            names = {
                " ".join(unicodedata.normalize("NFC", value).strip().split())
                for value in values
                if isinstance(value, str) and value.strip()
            }
            return tuple(sorted(names))

        board_signers = signer_names(
            [
                participant.get("name")
                for participant in board_participants
                if isinstance(participant, Mapping)
            ]
        )
        meeting_signers = signer_names(
            [
                general_meeting.get("chairName", general_meeting.get("chair_name")),
                general_meeting.get(
                    "coSignerName", general_meeting.get("co_signer_name")
                ),
            ]
        )
        required_signers = {
            kind.value: (
                board_signers
                if kind
                in {
                    CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL,
                    CorporateArtifactKind.ANNUAL_BOARD_MINUTES,
                }
                else meeting_signers
            )
            for kind in required_kinds
        }
        if any(not names for names in required_signers.values()):
            raise CorporateGovernanceError.unavailable()

        declared_amount_ore: int | None = None
        paid_amount_ore: int | None = None
        remaining_amount_ore: int | None = None
        if decision_kind is CorporateDecisionKind.OWNER_DIVIDEND:
            dividend = canonical.get("dividend")
            if not isinstance(dividend, Mapping):
                raise CorporateGovernanceError.unavailable()
            declared = dividend.get("amountOre", dividend.get("amount_ore"))
            if isinstance(declared, bool) or not isinstance(declared, int) or declared <= 0:
                raise CorporateGovernanceError.unavailable()
            paid = 0
            for event in events:
                if event.event_kind != "payment_recorded":
                    continue
                amount = event.metadata.get(
                    "amountOre", event.metadata.get("amount_ore")
                )
                if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
                    raise CorporateGovernanceError.unavailable()
                paid += amount
            if paid > declared:
                raise CorporateGovernanceError.unavailable()
            declared_amount_ore = declared
            paid_amount_ore = paid
            remaining_amount_ore = declared - paid

        if "rejected" in event_kinds:
            state = OwnerDividendState.REJECTED
        elif "superseded" in event_kinds:
            state = OwnerDividendState.SUPERSEDED
        elif finalization is not None:
            if remaining_amount_ore == 0:
                state = OwnerDividendState.PAID
            elif paid_amount_ore:
                state = OwnerDividendState.PARTIALLY_PAID
            else:
                state = OwnerDividendState.FINALIZED
        elif signed_complete:
            state = OwnerDividendState.SIGNED_OWNER_ATTESTED
        elif "signing_requested" in event_kinds:
            state = OwnerDividendState.SIGNING_REQUESTED
        elif "facts_approved" in event_kinds:
            state = OwnerDividendState.FACTS_APPROVED
        elif generated_complete:
            state = OwnerDividendState.DOCUMENTS_REGISTERED
        else:
            state = OwnerDividendState.PROPOSED

        blockers: list[CorporateDocumentReadinessBlocker] = []
        if current_source_matches is False:
            blockers.append(
                CorporateDocumentReadinessBlocker(
                    "corporate_documents_current_hash_mismatch",
                    "Beslutningsdokumentene er basert på et eldre årsgrunnlag.",
                )
            )
        if state in {
            OwnerDividendState.REJECTED,
            OwnerDividendState.SUPERSEDED,
        }:
            blockers.append(
                CorporateDocumentReadinessBlocker(
                    "corporate_documents_terminal_decision",
                    "Beslutningen er avvist eller erstattet og kan ikke brukes.",
                )
            )
        if not generated_complete:
            blockers.append(
                CorporateDocumentReadinessBlocker(
                    "corporate_documents_missing_required_artifacts",
                    "Alle genererte beslutningsdokumenter må finnes.",
                )
            )
        if "facts_approved" not in event_kinds:
            blockers.append(
                CorporateDocumentReadinessBlocker(
                    "corporate_documents_facts_approval_required",
                    "Fakta og dokumenthash må godkjennes av eier.",
                )
            )
        if not signed_complete:
            blockers.append(
                CorporateDocumentReadinessBlocker(
                    "corporate_documents_missing_signed_artifacts",
                    "Alle signerte dokumenter må lastes opp og eierbekreftes.",
                )
            )
        if finalization is None:
            blockers.append(
                CorporateDocumentReadinessBlocker(
                    "corporate_documents_finalization_required",
                    "Beslutningen må sluttføres etter signering.",
                )
            )

        source_is_current = current_source_matches is not False
        ready_for_signing = (
            source_is_current
            and state
            not in {
                OwnerDividendState.REJECTED,
                OwnerDividendState.SUPERSEDED,
            }
            and generated_complete
            and "facts_approved" in event_kinds
        )
        finalized = (
            finalization is not None
            and source_is_current
            and state
            not in {
                OwnerDividendState.REJECTED,
                OwnerDividendState.SUPERSEDED,
            }
        )
        return CorporateDocumentReadiness(
            company_id=company_id,
            income_year=income_year,
            decision_kind=decision_kind,
            decision_id=decision.decision_id,
            document_set_id=decision.document_set_id,
            decision_hash=decision.decision_hash,
            source_hash=decision.source_hash,
            current_source_hash=current_source_hash,
            state=state,
            current_source_matches=current_source_matches,
            ready_for_signing=ready_for_signing,
            finalized=finalized,
            annual_submission_ready=(
                decision_kind is CorporateDecisionKind.ANNUAL_CLOSE and finalized
            ),
            generated_artifact_hashes=generated,
            signed_artifact_hashes=signed,
            required_signers=required_signers,
            declared_amount_ore=declared_amount_ore,
            paid_amount_ore=paid_amount_ore,
            remaining_amount_ore=remaining_amount_ore,
            finalization_id=(
                finalization.finalization_id if finalization is not None else None
            ),
            accounting_policy_version=(
                finalization.accounting_policy_version
                if finalization is not None
                else None
            ),
            blockers=tuple(blockers),
        )

    def render_corporate_documents(
        self,
        decision: CanonicalOwnerDividendDecision | CanonicalAnnualCloseDecision,
    ) -> tuple[RenderedCorporateArtifact, ...]:
        return render_corporate_documents(decision)

    def validate_shareholder_loan(
        self,
        command: RecordShareholderLoanCommand,
    ) -> CanonicalShareholderLoan:
        if command.loan_date.value.year != int(command.income_year):
            _fail(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                "Shareholder-loan date must belong to the company year.",
            )
        if command.amount.currency.value != "NOK" or command.amount.amount <= 0:
            _fail(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                "Shareholder-loan amount must be positive NOK.",
            )
        if not isinstance(command.direction, ShareholderLoanDirection):
            _fail(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                "Shareholder-loan direction is invalid.",
            )
        if command.direction is ShareholderLoanDirection.COMPANY_TO_PERSONAL_SHAREHOLDER:
            _fail(
                CorporateGovernanceErrorCode.PERSONAL_SHAREHOLDER_LOAN_BLOCKED,
                "A company loan to a personal shareholder requires accountant review.",
            )
        if command.related_party_security is not False:
            _fail(
                CorporateGovernanceErrorCode.RELATED_PARTY_SECURITY_BLOCKED,
                "Related-party security or guarantees require accountant review.",
            )
        if not isinstance(command.document_status, ShareholderLoanDocumentStatus):
            _fail(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                "Shareholder-loan document status is invalid.",
            )
        if not isinstance(command.interest_modelled, bool):
            _fail(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                "Shareholder-loan interest evidence is invalid.",
            )
        counterparty_name = _text(command.counterparty_name)
        if len(counterparty_name) > 255:
            _fail(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                "Shareholder-loan counterparty is too long.",
            )
        amount_ore = int(command.amount.amount * 100)
        return CanonicalShareholderLoan(
            action_id=command.action_id,
            company_id=command.company_id,
            income_year=command.income_year,
            loan_date=command.loan_date,
            amount_ore=amount_ore,
            direction=command.direction,
            counterparty_name=counterparty_name,
            document_status=command.document_status,
            interest_modelled=command.interest_modelled,
            related_party_security=False,
            bank_transaction_id=command.bank_transaction_id,
            document_id=command.document_id,
        )

    def build_annual_close_decision(
        self,
        command: AnnualCloseProposalCommand,
    ) -> CanonicalAnnualCloseDecision:
        prepared = _prepare_decision_facts(command)
        basis = prepared.basis
        annual_result_allocation_ore = _safe_integer(
            command.annual_result_allocation_ore,
            minimum=-(2**53 - 1),
        )
        if (
            basis.income_year != command.income_year
            or annual_result_allocation_ore != basis.result_after_tax_ore
        ):
            _fail(
                CorporateGovernanceErrorCode.ANNUAL_RESULT_MISMATCH,
                "The result allocation does not match the approved annual basis.",
            )

        provisional = CanonicalAnnualCloseDecision(
            decision_id=command.decision_id,
            document_set_id=command.document_set_id,
            company_id=command.company_id,
            organization_number=prepared.organization_number,
            legal_name=prepared.legal_name,
            income_year=command.income_year,
            annual_close_source_id=basis.source_id,
            source_hash=prepared.source_hash,
            template_family=_TEMPLATE_FAMILY,
            template_version=_TEMPLATE_VERSION,
            annual_basis_year=basis.income_year,
            financial_totals=OwnerDividendFinancialTotals(
                basis.result_after_tax_ore,
                basis.equity_ore,
                basis.available_distribution_ore,
                basis.cash_ore,
            ),
            board_meeting=prepared.board_meeting,
            board_participants=prepared.board_participants,
            general_meeting=prepared.general_meeting,
            shareholders=prepared.decision_shareholders,
            total_company_shares=prepared.total_company_shares,
            one_share_class_confirmed=command.one_share_class_confirmed,
            dividend=None,
            annual_result_allocation_ore=annual_result_allocation_ore,
            confirmations=OwnerDividendConfirmations(
                basis.latest_approved,
                command.supported_dividend_basis_confirmed,
                command.full_board_participation_confirmed,
                prepared.full_representation,
                command.unanimous_board_confirmed,
                prepared.unanimous_shareholders,
                True,
                command.prudent_equity_and_liquidity_confirmed,
            ),
            decision_hash="",
        )
        return replace(
            provisional,
            decision_hash=_sha256(
                _canonical_json(canonical_annual_close_payload(provisional))
            ),
        )

    def build_owner_dividend_decision(
        self,
        command: OwnerDividendProposalCommand,
    ) -> CanonicalOwnerDividendDecision:
        prepared = _prepare_decision_facts(command)
        basis = prepared.basis
        amount_ore = _safe_integer(command.dividend_amount_ore, minimum=1)
        if command.payment_date.value < prepared.general_meeting.meeting_date.value:
            _fail(
                CorporateGovernanceErrorCode.UNSUPPORTED_DIVIDEND_BASIS,
                "Payment cannot precede the dividend decision.",
            )
        allocations: list[tuple[str, int, int, int]] = []
        allocated = 0
        for order, shareholder in enumerate(prepared.shareholders):
            quotient, remainder = divmod(
                amount_ore * shareholder.share_count,
                prepared.total_company_shares,
            )
            allocations.append(
                (shareholder.shareholder_id, quotient, remainder, order)
            )
            allocated += quotient
        remainder_order = sorted(allocations, key=lambda item: (-item[2], item[3]))
        bonuses = {
            shareholder_id
            for shareholder_id, _, _, _ in remainder_order[: amount_ore - allocated]
        }
        final_allocations = tuple(
            OwnerDividendAllocation(
                shareholder_id,
                quotient + (1 if shareholder_id in bonuses else 0),
            )
            for shareholder_id, quotient, _, _ in allocations
        )
        if any(allocation.amount_ore <= 0 for allocation in final_allocations):
            _fail(
                CorporateGovernanceErrorCode.ZERO_ALLOCATION,
                "Every owner allocation must be positive.",
            )
        liquidity_after_payment_ore = basis.cash_ore - amount_ore
        if (
            not command.prudent_equity_and_liquidity_confirmed
            or amount_ore > basis.available_distribution_ore
            or liquidity_after_payment_ore < 0
        ):
            _fail(
                CorporateGovernanceErrorCode.EQUITY_OR_LIQUIDITY_FAILED,
                "The dividend exceeds the supported equity or liquidity basis.",
            )

        provisional = CanonicalOwnerDividendDecision(
            decision_id=command.decision_id,
            document_set_id=command.document_set_id,
            company_id=command.company_id,
            organization_number=prepared.organization_number,
            legal_name=prepared.legal_name,
            income_year=command.income_year,
            annual_close_source_id=basis.source_id,
            source_hash=prepared.source_hash,
            template_family=_TEMPLATE_FAMILY,
            template_version=_TEMPLATE_VERSION,
            annual_basis_year=basis.income_year,
            financial_totals=OwnerDividendFinancialTotals(
                basis.result_after_tax_ore,
                basis.equity_ore,
                basis.available_distribution_ore,
                basis.cash_ore,
            ),
            board_meeting=prepared.board_meeting,
            board_participants=prepared.board_participants,
            general_meeting=prepared.general_meeting,
            shareholders=prepared.decision_shareholders,
            total_company_shares=prepared.total_company_shares,
            one_share_class_confirmed=command.one_share_class_confirmed,
            dividend=OwnerDividendFacts(
                amount_ore,
                command.payment_date,
                liquidity_after_payment_ore,
                final_allocations,
            ),
            annual_result_allocation_ore=basis.result_after_tax_ore,
            confirmations=OwnerDividendConfirmations(
                basis.latest_approved,
                command.supported_dividend_basis_confirmed,
                command.full_board_participation_confirmed,
                prepared.full_representation,
                command.unanimous_board_confirmed,
                prepared.unanimous_shareholders,
                True,
                command.prudent_equity_and_liquidity_confirmed,
            ),
            decision_hash="",
        )
        decision_hash = _sha256(
            _canonical_json(canonical_owner_dividend_payload(provisional))
        )
        return replace(provisional, decision_hash=decision_hash)


__all__ = [
    "CorporateGovernanceService",
    "canonical_owner_dividend_payload",
]
