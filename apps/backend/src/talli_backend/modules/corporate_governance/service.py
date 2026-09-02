"""Deterministic corporate-governance policy."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import replace
from enum import Enum
from typing import Any

from talli_backend.modules.corporate_governance.public import (
    BoardMeeting,
    CanonicalBoardParticipant,
    CanonicalDecisionShareholder,
    CanonicalOwnerDividendDecision,
    CorporateGovernanceError,
    CorporateGovernanceErrorCode,
    GeneralMeeting,
    OwnerDividendAllocation,
    OwnerDividendConfirmations,
    OwnerDividendFacts,
    OwnerDividendFinancialTotals,
    OwnerDividendProposalCommand,
    SHA256_PATTERN,
    ShareholderVote,
)


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
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        _json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _source_hash(command: OwnerDividendProposalCommand) -> str:
    basis = command.annual_basis
    if not SHA256_PATTERN.fullmatch(basis.annual_data_sha256) or not SHA256_PATTERN.fullmatch(
        basis.annual_accounts_payload_sha256
    ):
        _fail(
            CorporateGovernanceErrorCode.INVALID_INPUT,
            "Annual basis requires exact SHA-256 identities.",
        )
    return _sha256(
        _canonical_json(
            {
                "annual_accounts_payload_hash": basis.annual_accounts_payload_sha256,
                "annual_close_source_id": str(basis.source_id),
                "annual_data_hash": basis.annual_data_sha256,
            }
        )
    )


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


class CorporateGovernanceService:
    def build_owner_dividend_decision(
        self,
        command: OwnerDividendProposalCommand,
    ) -> CanonicalOwnerDividendDecision:
        if command.company.company_id != command.company_id:
            _fail(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                "Company identity does not match the proposal scope.",
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
        source_hash = _source_hash(command)

        shareholders = sorted(
            (
                replace(
                    shareholder,
                    shareholder_id=_text(shareholder.shareholder_id),
                    name=_text(shareholder.name),
                )
                for shareholder in command.shareholders
            ),
            key=lambda shareholder: (shareholder.order, shareholder.shareholder_id),
        )
        if not shareholders or len({item.shareholder_id for item in shareholders}) != len(
            shareholders
        ):
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
                (
                    _text(item.shareholder_id),
                    _text(item.name),
                    item.share_count,
                )
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
            or reviewed.available_distribution_ore != basis.available_distribution_ore
            or reviewed.annual_data_sha256 != basis.annual_data_sha256
            or reviewed.annual_accounts_payload_sha256
            != basis.annual_accounts_payload_sha256
        ):
            _fail(
                CorporateGovernanceErrorCode.REVIEWED_FACTS_CHANGED,
                "Reviewed facts changed before the proposal was submitted.",
            )

        participants = sorted(
            (
                replace(
                    participant,
                    participant_id=_text(participant.participant_id),
                    name=_text(participant.name),
                )
                for participant in command.board_participants
            ),
            key=lambda participant: (participant.order, participant.participant_id),
        )
        if not participants or len({item.participant_id for item in participants}) != len(
            participants
        ):
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
        decision_shareholders = []
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

        board_meeting = replace(command.board_meeting, place=_text(command.board_meeting.place))
        general_meeting = replace(
            command.general_meeting,
            place=_text(command.general_meeting.place),
            chair_name=_text(command.general_meeting.chair_name),
            co_signer_name=_text(command.general_meeting.co_signer_name),
        )
        if general_meeting.meeting_date.value < board_meeting.meeting_date.value:
            _fail(
                CorporateGovernanceErrorCode.UNSUPPORTED_DIVIDEND_BASIS,
                "The general meeting cannot precede the board proposal.",
            )
        if (
            not command.one_share_class_confirmed
            or not command.supported_dividend_basis_confirmed
        ):
            _fail(
                CorporateGovernanceErrorCode.UNSUPPORTED_DIVIDEND_BASIS,
                "The dividend basis is outside the supported path.",
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
                "Only unanimous owner-dividend decisions are supported.",
            )

        amount_ore = _safe_integer(command.dividend_amount_ore, minimum=1)
        if command.payment_date.value < general_meeting.meeting_date.value:
            _fail(
                CorporateGovernanceErrorCode.UNSUPPORTED_DIVIDEND_BASIS,
                "Payment cannot precede the dividend decision.",
            )
        allocations: list[tuple[str, int, int, int]] = []
        allocated = 0
        for order, shareholder in enumerate(shareholders):
            quotient, remainder = divmod(
                amount_ore * shareholder.share_count,
                total_company_shares,
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
            organization_number=organization_number,
            legal_name=legal_name,
            income_year=command.income_year,
            annual_close_source_id=basis.source_id,
            source_hash=source_hash,
            template_family=_TEMPLATE_FAMILY,
            template_version=_TEMPLATE_VERSION,
            annual_basis_year=basis.income_year,
            financial_totals=OwnerDividendFinancialTotals(
                basis.result_after_tax_ore,
                basis.equity_ore,
                basis.available_distribution_ore,
                basis.cash_ore,
            ),
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
            shareholders=tuple(decision_shareholders),
            total_company_shares=total_company_shares,
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
                full_representation,
                command.unanimous_board_confirmed,
                unanimous_shareholders,
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
