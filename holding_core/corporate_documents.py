from __future__ import annotations

import hashlib
import io
import json
from datetime import date, time
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import UUID
from xml.sax.saxutils import escape

from pydantic import BaseModel, ConfigDict, Field, field_validator
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


TEMPLATE_FAMILY = "norwegian_simple_as"
TEMPLATE_VERSION = "corporate-no-v1-reportlab-5.0.0-noto-ffebf8c1"
FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
FONT_REGULAR = "TalliNotoSans"
FONT_BOLD = "TalliNotoSansBold"


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


class RenderedCorporateArtifact(FrozenModel):
    artifact_kind: CorporateArtifactKind
    filename: str
    template_version: str
    decision_hash: str
    content_sha256: str
    byte_length: int = Field(gt=0)
    pdf_bytes: bytes


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


def render_corporate_documents(
    decision: CorporateDecisionInput,
) -> tuple[RenderedCorporateArtifact, ...]:
    validate_supported_scope(decision)
    _register_fonts()
    decision_hash = decision_sha256(decision)
    artifacts = []
    for artifact_kind in required_artifact_kinds(decision):
        pdf_bytes = _render_pdf(decision, artifact_kind, decision_hash)
        artifacts.append(
            RenderedCorporateArtifact(
                artifact_kind=artifact_kind,
                filename=_artifact_filename(artifact_kind),
                template_version=decision.template_version,
                decision_hash=decision_hash,
                content_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
                byte_length=len(pdf_bytes),
                pdf_bytes=pdf_bytes,
            )
        )
    return tuple(artifacts)


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


def _register_fonts() -> None:
    if FONT_REGULAR not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_REGULAR, FONT_DIR / "NotoSans-Regular.ttf"))
    if FONT_BOLD not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_BOLD, FONT_DIR / "NotoSans-Bold.ttf"))
    pdfmetrics.registerFontFamily(
        "TalliNoto",
        normal=FONT_REGULAR,
        bold=FONT_BOLD,
        italic=FONT_REGULAR,
        boldItalic=FONT_BOLD,
    )


def _render_pdf(
    decision: CorporateDecisionInput,
    artifact_kind: CorporateArtifactKind,
    decision_hash: str,
) -> bytes:
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=_artifact_title(artifact_kind),
        author="Talli",
        subject=f"{artifact_kind.value} {decision.template_version}",
        creator=f"Talli {decision.template_version}",
        displayDocTitle=True,
    )
    styles = _document_styles()
    story = _artifact_story(decision, artifact_kind, decision_hash, styles)
    document.build(story, canvasmaker=_deterministic_canvas)
    return buffer.getvalue()


def _deterministic_canvas(*args: object, **kwargs: object) -> canvas.Canvas:
    kwargs["invariant"] = 1
    kwargs["pageCompression"] = 1
    return canvas.Canvas(*args, **kwargs)


def _document_styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TalliTitle",
            parent=sample["Title"],
            fontName=FONT_BOLD,
            fontSize=18,
            leading=22,
            alignment=TA_CENTER,
            spaceAfter=8 * mm,
        ),
        "heading": ParagraphStyle(
            "TalliHeading",
            parent=sample["Heading2"],
            fontName=FONT_BOLD,
            fontSize=11,
            leading=14,
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "TalliBody",
            parent=sample["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=9.5,
            leading=13,
            spaceAfter=2.5 * mm,
        ),
        "small": ParagraphStyle(
            "TalliSmall",
            parent=sample["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#4b5563"),
            spaceBefore=4 * mm,
        ),
        "signature": ParagraphStyle(
            "TalliSignature",
            parent=sample["BodyText"],
            fontName=FONT_REGULAR,
            fontSize=9,
            leading=12,
            spaceBefore=7 * mm,
        ),
    }


def _artifact_story(
    decision: CorporateDecisionInput,
    artifact_kind: CorporateArtifactKind,
    decision_hash: str,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    story: list[object] = [
        Paragraph(_safe(_artifact_title(artifact_kind)), styles["title"]),
        Paragraph(
            f"<b>{_safe(decision.legal_name)}</b><br/>Organisasjonsnummer: {_format_org_number(decision.organization_number)}",
            styles["body"],
        ),
    ]
    if artifact_kind == CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL:
        story.extend(_dividend_board_story(decision, styles))
    elif artifact_kind == CorporateArtifactKind.DIVIDEND_GENERAL_MEETING_MINUTES:
        story.extend(_dividend_general_meeting_story(decision, styles))
    elif artifact_kind == CorporateArtifactKind.ANNUAL_BOARD_MINUTES:
        story.extend(_annual_board_story(decision, styles))
    else:
        story.extend(_annual_general_meeting_story(decision, styles))
    story.append(
        Paragraph(
            f"Dokumentversjon: {_safe(decision.template_version)}<br/>Beslutningshash (SHA-256): {decision_hash}",
            styles["small"],
        )
    )
    return story


def _dividend_board_story(
    decision: CorporateDecisionInput,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    dividend = _required_dividend(decision)
    rows = [
        ["Møtedato", _format_date(decision.board_meeting.meeting_date)],
        ["Tid", _format_time(decision.board_meeting.meeting_time)],
        ["Sted", decision.board_meeting.place],
        ["Behandlingsform", _treatment_label(decision.board_meeting.treatment_method)],
    ]
    story = _meeting_intro("Styremøte", rows, decision.board_participants, styles)
    story.extend(
        [
            Paragraph("Grunnlag og vurdering", styles["heading"]),
            Paragraph(
                "Forslaget bygger på godkjent årsregnskap for "
                f"{decision.annual_basis_year}. Fri egenkapital for utdeling er "
                f"{_format_money(decision.financial_totals.available_distribution_ore)}. "
                f"Foreslått kontantutbytte er {_format_money(dividend.amount_ore)}.",
                styles["body"],
            ),
            Paragraph(
                "Styret har vurdert selskapets egenkapital og likviditet som forsvarlig etter utdelingen. "
                f"Likviditet etter planlagt betaling er {_format_money(dividend.liquidity_after_payment_ore)}.",
                styles["body"],
            ),
            Paragraph("Styrets enstemmige forslag", styles["heading"]),
            Paragraph(
                f"Styret foreslår at generalforsamlingen vedtar et samlet kontantutbytte på "
                f"{_format_money(dividend.amount_ore)}, med betalingsdato {_format_date(dividend.payment_date)}. "
                "Utbyttet fordeles proporsjonalt etter registrert aksjeeierskap.",
                styles["body"],
            ),
            _allocation_table(decision, styles),
            *_board_signatures(decision, styles),
        ]
    )
    return story


def _dividend_general_meeting_story(
    decision: CorporateDecisionInput,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    dividend = _required_dividend(decision)
    story = _general_meeting_intro(decision, styles)
    story.extend(
        [
            Paragraph("Styrets forslag", styles["heading"]),
            Paragraph(
                f"Generalforsamlingen behandlet styrets forslag om kontantutbytte på "
                f"{_format_money(dividend.amount_ore)} basert på godkjent årsregnskap for "
                f"{decision.annual_basis_year}.",
                styles["body"],
            ),
            Paragraph("Enstemmig vedtak", styles["heading"]),
            Paragraph(
                f"Generalforsamlingen vedtok et samlet kontantutbytte på "
                f"{_format_money(dividend.amount_ore)}. Beløpet overstiger ikke styrets forslag. "
                f"Betalingsdato er {_format_date(dividend.payment_date)}.",
                styles["body"],
            ),
            _allocation_table(decision, styles),
            *_general_meeting_signatures(decision, styles),
        ]
    )
    return story


def _annual_board_story(
    decision: CorporateDecisionInput,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    rows = [
        ["Møtedato", _format_date(decision.board_meeting.meeting_date)],
        ["Tid", _format_time(decision.board_meeting.meeting_time)],
        ["Sted", decision.board_meeting.place],
        ["Behandlingsform", _treatment_label(decision.board_meeting.treatment_method)],
    ]
    story = _meeting_intro("Styremøte", rows, decision.board_participants, styles)
    story.extend(
        [
            Paragraph("Behandling av årsregnskapet", styles["heading"]),
            Paragraph(
                f"Styret behandlet årsregnskapet med noter for regnskapsåret {decision.income_year}. "
                f"Årsresultatet etter skatt er {_format_money(decision.financial_totals.result_after_tax_ore)}, "
                f"og egenkapitalen er {_format_money(decision.financial_totals.equity_ore)}.",
                styles["body"],
            ),
            Paragraph(
                f"Styret foreslår at {_format_money(decision.annual_result_allocation_ore)} disponeres i samsvar "
                "med årsregnskapet og legges frem for ordinær generalforsamling.",
                styles["body"],
            ),
            Paragraph(
                "Denne protokollen erstatter ikke kravet om at det separate årsregnskapet signeres av alle "
                "styremedlemmer og eventuell daglig leder.",
                styles["body"],
            ),
            Paragraph("Enstemmig vedtak", styles["heading"]),
            Paragraph("Styret vedtok å fremme årsregnskapet og resultatdisponeringen for generalforsamlingen.", styles["body"]),
            *_board_signatures(decision, styles),
        ]
    )
    return story


def _annual_general_meeting_story(
    decision: CorporateDecisionInput,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    story = _general_meeting_intro(decision, styles)
    story.extend(
        [
            Paragraph("Årsregnskap og resultatdisponering", styles["heading"]),
            Paragraph(
                f"Generalforsamlingen behandlet styrets forslag til årsregnskap med noter for "
                f"regnskapsåret {decision.income_year}. Årsresultatet etter skatt er "
                f"{_format_money(decision.financial_totals.result_after_tax_ore)}.",
                styles["body"],
            ),
            Paragraph("Enstemmig vedtak", styles["heading"]),
            Paragraph(
                "Generalforsamlingen godkjente årsregnskapet med noter og vedtok styrets forslag til "
                f"resultatdisponering på {_format_money(decision.annual_result_allocation_ore)}.",
                styles["body"],
            ),
            Paragraph(
                "Komplette årsregnskapsdokumenter skal sendes til Regnskapsregisteret innen gjeldende frist.",
                styles["body"],
            ),
            *_general_meeting_signatures(decision, styles),
        ]
    )
    return story


def _meeting_intro(
    label: str,
    rows: list[list[str]],
    participants: tuple[BoardParticipant, ...],
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    return [
        Paragraph(label, styles["heading"]),
        _fact_table(rows, styles),
        Paragraph("Deltakere", styles["heading"]),
        _fact_table([[participant.name, _board_role_label(participant.role)] for participant in participants], styles),
    ]


def _general_meeting_intro(
    decision: CorporateDecisionInput,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    meeting = decision.general_meeting
    rows = [
        ["Møtedato", _format_date(meeting.meeting_date)],
        ["Tid", _format_time(meeting.meeting_time)],
        ["Sted", meeting.place],
        ["Møteform", _meeting_form_label(meeting.meeting_form)],
        ["Møteleder", meeting.chair_name],
        ["Medundertegner", meeting.co_signer_name],
    ]
    shareholder_rows = [["Aksjonær", "Representerte aksjer", "Stemme"]]
    shareholder_rows.extend(
        [shareholder.name, str(shareholder.represented_share_count), "For"]
        for shareholder in decision.shareholders
    )
    return [
        Paragraph("Møteopplysninger", styles["heading"]),
        _fact_table(rows, styles),
        Paragraph("Representasjon og avstemning", styles["heading"]),
        _data_table(shareholder_rows, (80 * mm, 45 * mm, 30 * mm), styles),
        Paragraph(
            f"Alle selskapets {decision.total_company_shares} aksjer i én aksjeklasse var representert. "
            "Samtlige avgitte stemmer var for vedtakene.",
            styles["body"],
        ),
    ]


def _allocation_table(
    decision: CorporateDecisionInput,
    styles: dict[str, ParagraphStyle],
) -> Table:
    dividend = _required_dividend(decision)
    allocations = {item.shareholder_id: item.amount_ore for item in dividend.allocations}
    rows = [["Aksjonær", "Aksjer", "Utbytte"]]
    rows.extend(
        [shareholder.name, str(shareholder.share_count), _format_money(allocations[shareholder.shareholder_id])]
        for shareholder in decision.shareholders
    )
    rows.append(["Totalt", str(decision.total_company_shares), _format_money(dividend.amount_ore)])
    return _data_table(rows, (80 * mm, 30 * mm, 45 * mm), styles)


def _fact_table(rows: list[list[str]], styles: dict[str, ParagraphStyle]) -> Table:
    return _data_table(rows, (45 * mm, 110 * mm), styles, header=False)


def _data_table(
    rows: list[list[str]],
    widths: tuple[float, ...],
    styles: dict[str, ParagraphStyle],
    *,
    header: bool = True,
) -> Table:
    body = [[Paragraph(_safe(cell), styles["body"]) for cell in row] for row in rows]
    table = Table(body, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands: list[tuple[object, ...]] = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        commands.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5eef7")),
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ]
        )
    table.setStyle(TableStyle(commands))
    return table


def _board_signatures(
    decision: CorporateDecisionInput,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    story: list[object] = [Paragraph("Signatur", styles["heading"])]
    for participant in decision.board_participants:
        story.extend(
            [
                Spacer(1, 5 * mm),
                Paragraph(
                    f"____________________________________<br/>{_safe(participant.name)}, "
                    f"{_board_role_label(participant.role)}",
                    styles["signature"],
                ),
            ]
        )
    return story


def _general_meeting_signatures(
    decision: CorporateDecisionInput,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    return [
        Paragraph("Signatur", styles["heading"]),
        Spacer(1, 5 * mm),
        Paragraph(
            f"____________________________________<br/>{_safe(decision.general_meeting.chair_name)}, møteleder",
            styles["signature"],
        ),
        Spacer(1, 5 * mm),
        Paragraph(
            f"____________________________________<br/>{_safe(decision.general_meeting.co_signer_name)}, medundertegner",
            styles["signature"],
        ),
    ]


def _artifact_title(kind: CorporateArtifactKind) -> str:
    return {
        CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL: "Styrets forslag til utbytte",
        CorporateArtifactKind.DIVIDEND_GENERAL_MEETING_MINUTES: "Protokoll fra generalforsamling – utbytte",
        CorporateArtifactKind.ANNUAL_BOARD_MINUTES: "Styrets behandling av årsregnskapet",
        CorporateArtifactKind.ANNUAL_GENERAL_MEETING_MINUTES: "Protokoll fra ordinær generalforsamling",
    }[kind]


def _artifact_filename(kind: CorporateArtifactKind) -> str:
    return {
        CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL: "styrets-forslag-til-utbytte.pdf",
        CorporateArtifactKind.DIVIDEND_GENERAL_MEETING_MINUTES: "generalforsamlingsprotokoll-utbytte.pdf",
        CorporateArtifactKind.ANNUAL_BOARD_MINUTES: "styreprotokoll-aarsregnskap.pdf",
        CorporateArtifactKind.ANNUAL_GENERAL_MEETING_MINUTES: "generalforsamlingsprotokoll-aarsregnskap.pdf",
    }[kind]


def _required_dividend(decision: CorporateDecisionInput) -> DividendDecisionFacts:
    if decision.dividend is None:
        raise CorporateDocumentValidationError(
            "Utbyttefakta mangler.",
            "corporate_documents_unsupported_dividend_basis",
        )
    return decision.dividend


def _format_org_number(value: str) -> str:
    return f"{value[:3]} {value[3:6]} {value[6:]}"


def _format_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _format_time(value: time) -> str:
    return value.strftime("%H:%M")


def _format_money(amount_ore: int) -> str:
    sign = "-" if amount_ore < 0 else ""
    whole, fraction = divmod(abs(amount_ore), 100)
    whole_text = f"{whole:,}".replace(",", " ")
    return f"{sign}{whole_text},{fraction:02d} kr"


def _treatment_label(value: str) -> str:
    return {"physical": "Fysisk møte", "video": "Videomøte", "written": "Skriftlig behandling"}[value]


def _meeting_form_label(value: str) -> str:
    return {"physical": "Fysisk møte", "video": "Videomøte"}[value]


def _board_role_label(value: str) -> str:
    return {"chair": "styreleder", "member": "styremedlem"}[value]


def _safe(value: object) -> str:
    return escape(str(value))
