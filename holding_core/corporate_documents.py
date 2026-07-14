from __future__ import annotations

import hashlib
import json
from datetime import date, time
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


TEMPLATE_FAMILY = "norwegian_simple_as"
TEMPLATE_VERSION = "corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1"


class CorporateArtifactKind(StrEnum):
    DIVIDEND_BOARD_PROPOSAL = "dividend_board_proposal"
    DIVIDEND_GENERAL_MEETING_MINUTES = "dividend_general_meeting_minutes"
    ANNUAL_BOARD_MINUTES = "annual_board_minutes"
    ANNUAL_GENERAL_MEETING_MINUTES = "annual_general_meeting_minutes"


class CorporateDocumentValidationError(ValueError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FinancialTotals(FrozenModel):
    result_after_tax_ore: int
    equity_ore: int = Field(ge=0)
    available_distribution_ore: int = Field(ge=0)
    cash_ore: int = Field(ge=0)


class BoardMeeting(FrozenModel):
    meeting_date: date
    meeting_time: time
    place: str = Field(min_length=1, max_length=200)
    treatment_method: Literal["physical", "video", "written"]

    @field_validator("place")
    @classmethod
    def normalize_place(cls, value: str) -> str:
        return _normalized_text(value)


class BoardParticipant(FrozenModel):
    participant_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    role: Literal["chair", "member"]

    @field_validator("participant_id", "name")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _normalized_text(value)


class GeneralMeeting(FrozenModel):
    meeting_date: date
    meeting_time: time
    place: str = Field(min_length=1, max_length=200)
    meeting_form: Literal["physical", "video"]
    chair_name: str = Field(min_length=1, max_length=200)
    co_signer_name: str = Field(min_length=1, max_length=200)

    @field_validator("place", "chair_name", "co_signer_name")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _normalized_text(value)


class DecisionShareholder(FrozenModel):
    shareholder_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    share_count: int = Field(gt=0)
    represented_share_count: int = Field(ge=0)
    vote: Literal["for", "against", "abstain"]

    @field_validator("shareholder_id", "name")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _normalized_text(value)


class DividendAllocation(FrozenModel):
    shareholder_id: str = Field(min_length=1, max_length=100)
    amount_ore: int = Field(gt=0)

    @field_validator("shareholder_id")
    @classmethod
    def normalize_shareholder_id(cls, value: str) -> str:
        return _normalized_text(value)


class DividendDecisionFacts(FrozenModel):
    amount_ore: int = Field(gt=0)
    payment_date: date
    liquidity_after_payment_ore: int = Field(ge=0)
    allocations: tuple[DividendAllocation, ...] = Field(min_length=1)


class CorporateDecisionConfirmations(FrozenModel):
    latest_approved_annual_accounts: bool
    supported_dividend_basis: bool
    full_board_participation: bool
    full_share_representation: bool
    unanimous_board: bool
    unanimous_shareholders: bool
    proportional_allocation: bool
    prudent_equity_and_liquidity: bool


class CorporateDecisionInput(FrozenModel):
    request_id: UUID
    company_id: UUID
    organization_number: str = Field(pattern=r"^[0-9]{9}$")
    legal_name: str = Field(min_length=1, max_length=200)
    income_year: int = Field(ge=2000, le=2100)
    decision_kind: Literal["owner_dividend", "annual_close"]
    annual_close_source_id: UUID
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    template_family: Literal["norwegian_simple_as"] = TEMPLATE_FAMILY
    template_version: Literal["corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1"] = TEMPLATE_VERSION
    annual_basis_year: int = Field(ge=2000, le=2100)
    financial_totals: FinancialTotals
    board_meeting: BoardMeeting
    board_participants: tuple[BoardParticipant, ...] = Field(min_length=1)
    general_meeting: GeneralMeeting
    shareholders: tuple[DecisionShareholder, ...] = Field(min_length=1)
    total_company_shares: int = Field(gt=0)
    one_share_class_confirmed: bool
    dividend: DividendDecisionFacts | None
    annual_result_allocation_ore: int
    confirmations: CorporateDecisionConfirmations

    @field_validator("legal_name")
    @classmethod
    def normalize_legal_name(cls, value: str) -> str:
        return _normalized_text(value)


def canonical_decision_json(decision: CorporateDecisionInput) -> bytes:
    payload = decision.model_dump(mode="json", exclude_none=False)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def decision_sha256(decision: CorporateDecisionInput) -> str:
    return hashlib.sha256(canonical_decision_json(decision)).hexdigest()


def required_artifact_kinds(decision: CorporateDecisionInput) -> tuple[CorporateArtifactKind, ...]:
    if decision.decision_kind == "owner_dividend":
        return (
            CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL,
            CorporateArtifactKind.DIVIDEND_GENERAL_MEETING_MINUTES,
        )
    return (
        CorporateArtifactKind.ANNUAL_BOARD_MINUTES,
        CorporateArtifactKind.ANNUAL_GENERAL_MEETING_MINUTES,
    )


def validate_supported_scope(decision: CorporateDecisionInput) -> None:
    confirmations = decision.confirmations
    if (
        not decision.one_share_class_confirmed
        or not confirmations.latest_approved_annual_accounts
        or not confirmations.supported_dividend_basis
        or decision.general_meeting.meeting_date < decision.board_meeting.meeting_date
    ):
        _blocked(
            "corporate_documents_unsupported_dividend_basis",
            "Beslutningen er utenfor støttet grunnlag for dokumentgenerering.",
        )

    participant_ids = [participant.participant_id for participant in decision.board_participants]
    if (
        not confirmations.full_board_participation
        or not participant_ids
        or len(participant_ids) != len(set(participant_ids))
    ):
        _blocked(
            "corporate_documents_incomplete_board",
            "Alle styremedlemmer må delta og være registrert én gang.",
        )

    shareholder_ids = [shareholder.shareholder_id for shareholder in decision.shareholders]
    owned_shares = sum(shareholder.share_count for shareholder in decision.shareholders)
    represented_shares = sum(shareholder.represented_share_count for shareholder in decision.shareholders)
    if (
        not confirmations.full_share_representation
        or len(shareholder_ids) != len(set(shareholder_ids))
        or owned_shares != decision.total_company_shares
        or represented_shares != decision.total_company_shares
        or any(
            shareholder.represented_share_count != shareholder.share_count
            for shareholder in decision.shareholders
        )
    ):
        _blocked(
            "corporate_documents_incomplete_share_representation",
            "Alle aksjer må være representert av registrerte aksjonærer.",
        )

    if (
        not confirmations.unanimous_board
        or not confirmations.unanimous_shareholders
        or any(shareholder.vote != "for" for shareholder in decision.shareholders)
    ):
        _blocked(
            "corporate_documents_non_unanimous",
            "Lanseringsløpet støtter bare enstemmige beslutninger.",
        )

    if decision.decision_kind == "owner_dividend":
        _validate_owner_dividend(decision)
    elif decision.dividend is not None:
        _blocked(
            "corporate_documents_unsupported_dividend_basis",
            "Årsavslutningsbeslutningen kan ikke inneholde et separat utbytte i dette løpet.",
        )


def _validate_owner_dividend(decision: CorporateDecisionInput) -> None:
    dividend = decision.dividend
    if dividend is None or dividend.payment_date < decision.general_meeting.meeting_date:
        _blocked(
            "corporate_documents_unsupported_dividend_basis",
            "Utbytte krever betalingsdato etter generalforsamlingens beslutning.",
        )

    allocation_ids = [allocation.shareholder_id for allocation in dividend.allocations]
    actual_allocations = {allocation.shareholder_id: allocation.amount_ore for allocation in dividend.allocations}
    expected_allocations = _proportional_allocations(decision, dividend.amount_ore)
    if (
        not decision.confirmations.proportional_allocation
        or len(allocation_ids) != len(set(allocation_ids))
        or set(allocation_ids) != {shareholder.shareholder_id for shareholder in decision.shareholders}
        or sum(actual_allocations.values()) != dividend.amount_ore
        or actual_allocations != expected_allocations
    ):
        _blocked(
            "corporate_documents_allocation_mismatch",
            "Utbyttet må fordeles proporsjonalt og summere til totalbeløpet.",
        )

    if (
        not decision.confirmations.prudent_equity_and_liquidity
        or dividend.amount_ore > decision.financial_totals.available_distribution_ore
        or dividend.liquidity_after_payment_ore < 0
        or dividend.liquidity_after_payment_ore
        != decision.financial_totals.cash_ore - dividend.amount_ore
    ):
        _blocked(
            "corporate_documents_equity_or_liquidity_failed",
            "Utbyttet består ikke kontrollen av utdelingsramme og likviditet.",
        )


def _proportional_allocations(decision: CorporateDecisionInput, amount_ore: int) -> dict[str, int]:
    allocations: dict[str, int] = {}
    remainders: list[tuple[int, int, str]] = []
    allocated = 0
    for order, shareholder in enumerate(decision.shareholders):
        quotient, remainder = divmod(amount_ore * shareholder.share_count, decision.total_company_shares)
        allocations[shareholder.shareholder_id] = quotient
        allocated += quotient
        remainders.append((-remainder, order, shareholder.shareholder_id))
    for _, _, shareholder_id in sorted(remainders)[: amount_ore - allocated]:
        allocations[shareholder_id] += 1
    return allocations


def _normalized_text(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise ValueError("value must contain non-whitespace characters")
    return normalized


def _blocked(code: str, message: str) -> None:
    raise CorporateDocumentValidationError(message, code)
