"""Deterministic in-process rendering owned by corporate governance."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from talli_backend.modules.corporate_governance.public import (
    CanonicalAnnualCloseDecision,
    CanonicalOwnerDividendDecision,
    CorporateArtifactKind,
    RenderedCorporateArtifact,
)


RenderableCorporateDecision = (
    CanonicalOwnerDividendDecision | CanonicalAnnualCloseDecision
)


FONT_REGULAR = "TalliNotoSans"
FONT_BOLD = "TalliNotoSansBold"
_FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"


def render_corporate_documents(
    decision: RenderableCorporateDecision,
) -> tuple[RenderedCorporateArtifact, ...]:
    _register_fonts()
    artifacts = []
    artifact_kinds = (
        (
            CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL,
            CorporateArtifactKind.DIVIDEND_GENERAL_MEETING_MINUTES,
        )
        if decision.dividend is not None
        else (
            CorporateArtifactKind.ANNUAL_BOARD_MINUTES,
            CorporateArtifactKind.ANNUAL_GENERAL_MEETING_MINUTES,
        )
    )
    for artifact_kind in artifact_kinds:
        pdf_bytes = _render_pdf(decision, artifact_kind)
        artifacts.append(
            RenderedCorporateArtifact(
                artifact_kind=artifact_kind,
                filename=_artifact_filename(artifact_kind),
                template_version=decision.template_version,
                decision_hash=decision.decision_hash,
                content_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
                byte_length=len(pdf_bytes),
                pdf_bytes=pdf_bytes,
            )
        )
    return tuple(artifacts)


def _font_dir() -> Path:
    return _FONT_DIR


def _register_fonts() -> None:
    font_dir = _font_dir()
    if FONT_REGULAR not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_REGULAR, font_dir / "NotoSans-Regular.ttf"))
    if FONT_BOLD not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_BOLD, font_dir / "NotoSans-Bold.ttf"))
    pdfmetrics.registerFontFamily(
        "TalliNoto",
        normal=FONT_REGULAR,
        bold=FONT_BOLD,
        italic=FONT_REGULAR,
        boldItalic=FONT_BOLD,
    )


def _render_pdf(
    decision: RenderableCorporateDecision,
    artifact_kind: CorporateArtifactKind,
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
    document.build(
        _artifact_story(decision, artifact_kind, _document_styles()),
        canvasmaker=_deterministic_canvas,
    )
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
    decision: RenderableCorporateDecision,
    artifact_kind: CorporateArtifactKind,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    story: list[object] = [
        Paragraph(_safe(_artifact_title(artifact_kind)), styles["title"]),
        Paragraph(
            f"<b>{_safe(decision.legal_name)}</b><br/>Organisasjonsnummer: "
            f"{_format_org_number(decision.organization_number)}",
            styles["body"],
        ),
    ]
    if artifact_kind == CorporateArtifactKind.DIVIDEND_BOARD_PROPOSAL:
        assert isinstance(decision, CanonicalOwnerDividendDecision)
        story.extend(_dividend_board_story(decision, styles))
    elif artifact_kind == CorporateArtifactKind.DIVIDEND_GENERAL_MEETING_MINUTES:
        assert isinstance(decision, CanonicalOwnerDividendDecision)
        story.extend(_dividend_general_meeting_story(decision, styles))
    elif artifact_kind == CorporateArtifactKind.ANNUAL_BOARD_MINUTES:
        story.extend(_annual_board_story(decision, styles))
    else:
        story.extend(_annual_general_meeting_story(decision, styles))
    story.append(
        Paragraph(
            f"Dokumentversjon: {_safe(decision.template_version)}<br/>"
            f"Beslutningshash (SHA-256): {decision.decision_hash}",
            styles["small"],
        )
    )
    return story


def _dividend_board_story(
    decision: CanonicalOwnerDividendDecision,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    dividend = decision.dividend
    rows = [
        ["Møtedato", _format_date(decision.board_meeting.meeting_date.value)],
        ["Tid", _format_time(decision.board_meeting.meeting_time)],
        ["Sted", decision.board_meeting.place],
        ["Behandlingsform", _treatment_label(decision.board_meeting.treatment_method.value)],
    ]
    story = _meeting_intro("Styremøte", rows, decision, styles)
    story.extend(
        [
            Paragraph("Grunnlag og vurdering", styles["heading"]),
            Paragraph(
                "Forslaget bygger på godkjent årsregnskap for "
                f"{int(decision.annual_basis_year)}. Fri egenkapital for utdeling er "
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
                "Styret foreslår at generalforsamlingen vedtar et samlet kontantutbytte på "
                f"{_format_money(dividend.amount_ore)}, med betalingsdato "
                f"{_format_date(dividend.payment_date.value)}. Utbyttet fordeles "
                "proporsjonalt etter registrert aksjeeierskap.",
                styles["body"],
            ),
            _allocation_table(decision, styles),
            *_board_signatures(decision, styles),
        ]
    )
    return story


def _dividend_general_meeting_story(
    decision: CanonicalOwnerDividendDecision,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    dividend = decision.dividend
    story = _general_meeting_intro(decision, styles)
    story.extend(
        [
            Paragraph("Styrets forslag", styles["heading"]),
            Paragraph(
                "Generalforsamlingen behandlet styrets forslag om kontantutbytte på "
                f"{_format_money(dividend.amount_ore)} basert på godkjent årsregnskap for "
                f"{int(decision.annual_basis_year)}.",
                styles["body"],
            ),
            Paragraph("Enstemmig vedtak", styles["heading"]),
            Paragraph(
                "Generalforsamlingen vedtok et samlet kontantutbytte på "
                f"{_format_money(dividend.amount_ore)}. Beløpet overstiger ikke styrets forslag. "
                f"Betalingsdato er {_format_date(dividend.payment_date.value)}.",
                styles["body"],
            ),
            _allocation_table(decision, styles),
            *_general_meeting_signatures(decision, styles),
        ]
    )
    return story


def _annual_board_story(
    decision: RenderableCorporateDecision,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    rows = [
        ["Møtedato", _format_date(decision.board_meeting.meeting_date.value)],
        ["Tid", _format_time(decision.board_meeting.meeting_time)],
        ["Sted", decision.board_meeting.place],
        ["Behandlingsform", _treatment_label(decision.board_meeting.treatment_method.value)],
    ]
    story = _meeting_intro("Styremøte", rows, decision, styles)
    story.extend(
        [
            Paragraph("Behandling av årsregnskapet", styles["heading"]),
            Paragraph(
                "Styret behandlet årsregnskapet med noter for regnskapsåret "
                f"{int(decision.income_year)}. Årsresultatet etter skatt er "
                f"{_format_money(decision.financial_totals.result_after_tax_ore)}, "
                f"og egenkapitalen er {_format_money(decision.financial_totals.equity_ore)}.",
                styles["body"],
            ),
            Paragraph(
                f"Styret foreslår at {_format_money(decision.annual_result_allocation_ore)} "
                "disponeres i samsvar med årsregnskapet og legges frem for ordinær "
                "generalforsamling.",
                styles["body"],
            ),
            Paragraph(
                "Denne protokollen erstatter ikke kravet om at det separate årsregnskapet "
                "signeres av alle styremedlemmer og eventuell daglig leder.",
                styles["body"],
            ),
            Paragraph("Enstemmig vedtak", styles["heading"]),
            Paragraph(
                "Styret vedtok å fremme årsregnskapet og resultatdisponeringen for generalforsamlingen.",
                styles["body"],
            ),
            *_board_signatures(decision, styles),
        ]
    )
    return story


def _annual_general_meeting_story(
    decision: RenderableCorporateDecision,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    story = _general_meeting_intro(decision, styles)
    story.extend(
        [
            Paragraph("Årsregnskap og resultatdisponering", styles["heading"]),
            Paragraph(
                "Generalforsamlingen behandlet styrets forslag til årsregnskap med noter for "
                f"regnskapsåret {int(decision.income_year)}. Årsresultatet etter skatt er "
                f"{_format_money(decision.financial_totals.result_after_tax_ore)}.",
                styles["body"],
            ),
            Paragraph("Enstemmig vedtak", styles["heading"]),
            Paragraph(
                "Generalforsamlingen godkjente årsregnskapet med noter og vedtok styrets "
                f"forslag til resultatdisponering på "
                f"{_format_money(decision.annual_result_allocation_ore)}.",
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
    decision: RenderableCorporateDecision,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    return [
        Paragraph(label, styles["heading"]),
        _fact_table(rows, styles),
        Paragraph("Deltakere", styles["heading"]),
        _fact_table(
            [
                [participant.name, _board_role_label(participant.role.value)]
                for participant in decision.board_participants
            ],
            styles,
        ),
    ]


def _general_meeting_intro(
    decision: RenderableCorporateDecision,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    meeting = decision.general_meeting
    rows = [
        ["Møtedato", _format_date(meeting.meeting_date.value)],
        ["Tid", _format_time(meeting.meeting_time)],
        ["Sted", meeting.place],
        ["Møteform", _meeting_form_label(meeting.meeting_form.value)],
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
    decision: CanonicalOwnerDividendDecision,
    styles: dict[str, ParagraphStyle],
) -> Table:
    allocations = {
        item.shareholder_id: item.amount_ore for item in decision.dividend.allocations
    }
    rows = [["Aksjonær", "Aksjer", "Utbytte"]]
    rows.extend(
        [
            shareholder.name,
            str(shareholder.share_count),
            _format_money(allocations[shareholder.shareholder_id]),
        ]
        for shareholder in decision.shareholders
    )
    rows.append(
        [
            "Totalt",
            str(decision.total_company_shares),
            _format_money(decision.dividend.amount_ore),
        ]
    )
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
    decision: RenderableCorporateDecision,
    styles: dict[str, ParagraphStyle],
) -> list[object]:
    story: list[object] = [Paragraph("Signatur", styles["heading"])]
    for participant in decision.board_participants:
        story.extend(
            [
                Spacer(1, 5 * mm),
                Paragraph(
                    f"____________________________________<br/>{_safe(participant.name)}, "
                    f"{_board_role_label(participant.role.value)}",
                    styles["signature"],
                ),
            ]
        )
    return story


def _general_meeting_signatures(
    decision: RenderableCorporateDecision,
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


def _format_org_number(value: str) -> str:
    return f"{value[:3]} {value[3:6]} {value[6:]}"


def _format_date(value: object) -> str:
    return value.strftime("%d.%m.%Y")


def _format_time(value: object) -> str:
    return value.strftime("%H:%M")


def _format_money(amount_ore: int) -> str:
    sign = "-" if amount_ore < 0 else ""
    whole, fraction = divmod(abs(amount_ore), 100)
    whole_text = f"{whole:,}".replace(",", " ")
    return f"{sign}{whole_text},{fraction:02d} kr"


def _treatment_label(value: str) -> str:
    return {
        "physical": "Fysisk møte",
        "video": "Videomøte",
        "written": "Skriftlig behandling",
    }[value]


def _meeting_form_label(value: str) -> str:
    return {"physical": "Fysisk møte", "video": "Videomøte"}[value]


def _board_role_label(value: str) -> str:
    return {"chair": "styreleder", "member": "styremedlem"}[value]


def _safe(value: object) -> str:
    return escape(str(value))


__all__ = ["render_corporate_documents"]
