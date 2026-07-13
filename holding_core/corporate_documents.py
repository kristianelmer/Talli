from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from html import escape
from io import BytesIO
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


NAVY = colors.HexColor("#10233F")
PALE_BLUE = colors.HexColor("#EAF2F8")
PALE_YELLOW = colors.HexColor("#FFF4D6")
MUTED = colors.HexColor("#526172")
RULE = colors.HexColor("#C8D3DE")


class DividendAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shareholder_id: str = Field(min_length=1, max_length=200)
    shareholder_name: str = Field(min_length=1, max_length=240)
    share_count: Decimal = Field(gt=0)
    amount: Decimal = Field(gt=0, decimal_places=2)


class DividendDocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(min_length=1, max_length=240)
    org_number: str
    income_year: int = Field(ge=2000, le=2100)
    decision_date: date
    payment_date: date
    total_amount: Decimal = Field(gt=0, decimal_places=2)
    distributable_equity: Decimal = Field(ge=0, decimal_places=2)
    liquidity_after_payment: Decimal = Field(ge=0, decimal_places=2)
    allocations: list[DividendAllocation] = Field(min_length=1, max_length=200)

    @field_validator("org_number")
    @classmethod
    def validate_org_number(cls, value: str) -> str:
        normalized = value.replace(" ", "")
        if len(normalized) != 9 or not normalized.isdigit():
            raise ValueError("org_number must contain exactly 9 digits")
        return normalized

    @model_validator(mode="after")
    def validate_amounts(self) -> "DividendDocumentInput":
        if self.payment_date < self.decision_date:
            raise ValueError("payment_date cannot be before decision_date")
        if self.total_amount > self.distributable_equity:
            raise ValueError("total_amount exceeds distributable_equity")
        if sum((allocation.amount for allocation in self.allocations), Decimal("0")) != self.total_amount:
            raise ValueError("allocation amounts must equal total_amount")
        if any(allocation.share_count != allocation.share_count.to_integral_value() for allocation in self.allocations):
            raise ValueError("share_count must be a whole number")
        if len({allocation.shareholder_id for allocation in self.allocations}) != len(self.allocations):
            raise ValueError("shareholder_id must be unique")
        total_shares = sum((allocation.share_count for allocation in self.allocations), Decimal("0"))
        if any(
            allocation.amount * total_shares != self.total_amount * allocation.share_count
            for allocation in self.allocations
        ):
            raise ValueError("allocations must use an equal amount per share")
        return self


@dataclass(frozen=True)
class GeneratedCorporateDocument:
    kind: Literal["board_proposal", "general_meeting_minutes"]
    file_name: str
    content_type: Literal["application/pdf"]
    content: bytes

    def json_record(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "file_name": self.file_name,
            "content_type": self.content_type,
            "base64": b64encode(self.content).decode("ascii"),
        }


def generate_owner_dividend_documents(data: DividendDocumentInput) -> tuple[GeneratedCorporateDocument, ...]:
    return (
        GeneratedCorporateDocument(
            kind="board_proposal",
            file_name="styreforslag-og-protokoll-utbytte.pdf",
            content_type="application/pdf",
            content=_render_document(data, "board_proposal"),
        ),
        GeneratedCorporateDocument(
            kind="general_meeting_minutes",
            file_name="generalforsamlingsprotokoll-utbytte.pdf",
            content_type="application/pdf",
            content=_render_document(data, "general_meeting_minutes"),
        ),
    )


def _render_document(
    data: DividendDocumentInput,
    kind: Literal["board_proposal", "general_meeting_minutes"],
) -> bytes:
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=22 * mm,
        bottomMargin=22 * mm,
        title=(
            "Styrets forslag og protokoll - utdeling av utbytte"
            if kind == "board_proposal"
            else "Protokoll fra generalforsamling - utdeling av utbytte"
        ),
        author="Talli",
        subject=f"Utkast til selskapsdokument for {data.company_name}",
        invariant=1,
        pageCompression=1,
    )
    styles = _styles()
    story = _board_story(data, styles) if kind == "board_proposal" else _general_meeting_story(data, styles)
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return output.getvalue()


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "DocumentTitle",
            parent=sample["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=NAVY,
            spaceAfter=12,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=sample["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=MUTED,
            spaceAfter=14,
        ),
        "heading": ParagraphStyle(
            "SectionHeading",
            parent=sample["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=NAVY,
            spaceBefore=12,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=14,
            textColor=colors.HexColor("#1D2A36"),
            spaceAfter=7,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=MUTED,
        ),
        "table": ParagraphStyle(
            "TableText",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#1D2A36"),
        ),
        "table_right": ParagraphStyle(
            "TableTextRight",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#1D2A36"),
            alignment=TA_RIGHT,
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=sample["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.white,
        ),
        "table_header_right": ParagraphStyle(
            "TableHeaderRight",
            parent=sample["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.white,
            alignment=TA_RIGHT,
        ),
        "draft": ParagraphStyle(
            "Draft",
            parent=sample["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#6C4B00"),
            alignment=TA_CENTER,
        ),
    }


def _common_intro(
    data: DividendDocumentInput,
    styles: dict[str, ParagraphStyle],
    title: str,
    decision_label: str,
) -> list[object]:
    return [
        _draft_banner(styles),
        Spacer(1, 7 * mm),
        Paragraph(escape(title), styles["title"]),
        Paragraph(
            "Selskapsdokument generert av Talli. Opplysninger, myndighet, datoer og ordlyd må "
            "kontrolleres før dokumentet signeres og får virkning.",
            styles["subtitle"],
        ),
        _metadata_table(data, styles, decision_label),
    ]


def _board_story(data: DividendDocumentInput, styles: dict[str, ParagraphStyle]) -> list[object]:
    story = _common_intro(
        data,
        styles,
        "Styrets forslag og protokoll - utdeling av utbytte",
        "Planlagt dato for generalforsamling",
    )
    story.extend(
        [
            Paragraph("1. Møtedetaljer", styles["heading"]),
            _key_value_table(
                [
                    ("Dato og klokkeslett", "____________________________________________"),
                    ("Møtested eller møteform", "____________________________________________"),
                    ("Tilstede", "____________________________________________"),
                    ("Forfall", "____________________________________________"),
                ],
                styles,
            ),
            Paragraph("2. Forslag om utdeling av utbytte", styles["heading"]),
            Paragraph(
                f"Styret behandlet forslag om ordinært kontantutbytte på <b>{_money(data.total_amount)}</b> "
                f"med planlagt betalingsdato {_date(data.payment_date)}.",
                styles["body"],
            ),
            _allocation_table(data, styles),
            Paragraph("3. Styrets forsvarlighetsvurdering", styles["heading"]),
            Paragraph(
                "Styret må før signering kontrollere at utdelingen ligger innenfor selskapets utdelingsgrunnlag, "
                "og at selskapet etter utdelingen fortsatt har forsvarlig egenkapital og likviditet.",
                styles["body"],
            ),
            _key_value_table(
                [
                    ("Oppgitt fri egenkapital", _money(data.distributable_equity)),
                    ("Oppgitt likviditet etter betaling", _money(data.liquidity_after_payment)),
                    ("Styrets kontroll og begrunnelse", "____________________________________________"),
                    ("", "____________________________________________"),
                ],
                styles,
            ),
            Paragraph("4. Forslag til vedtak", styles["heading"]),
            Paragraph(
                f"Styret foreslår at generalforsamlingen beslutter et samlet utbytte på "
                f"<b>{_money(data.total_amount)}</b>, fordelt som angitt ovenfor og med planlagt betaling "
                f"{_date(data.payment_date)}. Forslaget forutsetter at styrets vurdering i punkt 3 bekreftes.",
                styles["body"],
            ),
            Paragraph("5. Styrets beslutning", styles["heading"]),
            _checkbox_line("Forslaget ble enstemmig vedtatt av styret.", styles),
            _checkbox_line("Annen beslutning (beskriv): ____________________________________________", styles),
            Spacer(1, 6 * mm),
            _signature_block("Styrets medlemmer", styles, two_signatures=True),
        ]
    )
    return story


def _general_meeting_story(data: DividendDocumentInput, styles: dict[str, ParagraphStyle]) -> list[object]:
    story = _common_intro(
        data,
        styles,
        "Protokoll fra generalforsamling - utdeling av utbytte",
        "Beslutningsdato",
    )
    story.extend(
        [
            Paragraph("1. Åpning og møtedetaljer", styles["heading"]),
            _key_value_table(
                [
                    ("Dato og klokkeslett", f"{_date(data.decision_date)} / ____________________"),
                    ("Møtested eller møteform", "____________________________________________"),
                    ("Møteleder", "____________________________________________"),
                    ("Protokollunderskriver", "____________________________________________"),
                ],
                styles,
            ),
            Paragraph("2. Fremmøte og stemmer", styles["heading"]),
            Paragraph(
                "Kontroller at fremmøtte aksjeeiere, fullmakter, antall aksjer og stemmer er fullstendig angitt.",
                styles["body"],
            ),
            _attendance_table(data, styles),
            Paragraph("3. Godkjenning av innkalling og dagsorden", styles["heading"]),
            _checkbox_line("Innkalling og dagsorden ble godkjent.", styles),
            _checkbox_line("Merknader: __________________________________________________________", styles),
            Paragraph("4. Beslutning om utdeling av utbytte", styles["heading"]),
            Paragraph(
                f"Generalforsamlingen behandlet styrets forslag og besluttet et samlet kontantutbytte på "
                f"<b>{_money(data.total_amount)}</b>, fordelt som angitt nedenfor. Planlagt betalingsdato er "
                f"{_date(data.payment_date)}.",
                styles["body"],
            ),
            _allocation_table(data, styles),
            Paragraph(
                "Beslutningen må ligge innenfor styrets forslag eller aksept. Selskapets opplysninger og styrets "
                "forsvarlighetsvurdering må kontrolleres før signering.",
                styles["small"],
            ),
            Paragraph("5. Avstemning", styles["heading"]),
            _key_value_table(
                [
                    ("Stemmer for", "____________________"),
                    ("Stemmer mot", "____________________"),
                    ("Avstår", "____________________"),
                    ("Resultat", "____________________________________________"),
                ],
                styles,
            ),
            Paragraph("6. Signaturer", styles["heading"]),
            Paragraph(
                "Protokollen dateres og signeres i samsvar med selskapets forhold og gjeldende krav.",
                styles["body"],
            ),
            Spacer(1, 4 * mm),
            _signature_block("Møteleder og valgt medunderskriver", styles, two_signatures=True),
        ]
    )
    return story


def _draft_banner(styles: dict[str, ParagraphStyle]) -> Table:
    table = Table(
        [[Paragraph("UTKAST - MÅ KONTROLLERES OG SIGNERES", styles["draft"])]],
        colWidths=[170 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_YELLOW),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#D8A928")),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _metadata_table(
    data: DividendDocumentInput,
    styles: dict[str, ParagraphStyle],
    decision_label: str,
) -> Table:
    return _key_value_table(
        [
            ("Selskap", data.company_name),
            ("Organisasjonsnummer", _org_number(data.org_number)),
            ("Inntektsår", str(data.income_year)),
            (decision_label, _date(data.decision_date)),
        ],
        styles,
        shaded=True,
    )


def _key_value_table(
    rows: list[tuple[str, str]],
    styles: dict[str, ParagraphStyle],
    *,
    shaded: bool = False,
) -> Table:
    values = [
        [Paragraph(f"<b>{escape(label)}</b>", styles["table"]), Paragraph(escape(value), styles["table"])]
        for label, value in rows
    ]
    table = Table(values, colWidths=[52 * mm, 118 * mm], hAlign="LEFT")
    commands: list[tuple] = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.35, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if shaded:
        commands.extend([("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE), ("BOX", (0, 0), (-1, -1), 0.5, RULE)])
    table.setStyle(TableStyle(commands))
    return table


def _allocation_table(data: DividendDocumentInput, styles: dict[str, ParagraphStyle]) -> Table:
    rows: list[list[Paragraph]] = [
        [
            Paragraph("Aksjeeier", styles["table_header"]),
            Paragraph("Aksjer", styles["table_header_right"]),
            Paragraph("Beløp", styles["table_header_right"]),
        ]
    ]
    for allocation in data.allocations:
        rows.append(
            [
                Paragraph(escape(allocation.shareholder_name), styles["table"]),
                Paragraph(_number(allocation.share_count), styles["table_right"]),
                Paragraph(_money(allocation.amount), styles["table_right"]),
            ]
        )
    rows.append(
        [
            Paragraph("<b>Totalt</b>", styles["table"]),
            Paragraph(f"<b>{_number(sum(a.share_count for a in data.allocations))}</b>", styles["table_right"]),
            Paragraph(f"<b>{_money(data.total_amount)}</b>", styles["table_right"]),
        ]
    )
    table = Table(rows, colWidths=[92 * mm, 30 * mm, 48 * mm], repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, -1), (-1, -1), PALE_BLUE),
                ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, RULE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _attendance_table(data: DividendDocumentInput, styles: dict[str, ParagraphStyle]) -> Table:
    rows: list[list[Paragraph]] = [
        [
            Paragraph("Aksjeeier / fullmektig", styles["table_header"]),
            Paragraph("Aksjer", styles["table_header_right"]),
            Paragraph("Stemmer", styles["table_header_right"]),
            Paragraph("Fullmakt kontrollert", styles["table_header"]),
        ]
    ]
    for allocation in data.allocations:
        rows.append(
            [
                Paragraph(escape(allocation.shareholder_name), styles["table"]),
                Paragraph(_number(allocation.share_count), styles["table_right"]),
                Paragraph("________", styles["table_right"]),
                Paragraph("[ ] Ja&nbsp;&nbsp;[ ] Ikke relevant", styles["table"]),
            ]
        )
    table = Table(rows, colWidths=[73 * mm, 23 * mm, 25 * mm, 49 * mm], repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, RULE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _checkbox_line(text: str, styles: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(f"[ ]&nbsp;&nbsp;{escape(text)}", styles["body"])


def _signature_block(label: str, styles: dict[str, ParagraphStyle], *, two_signatures: bool) -> KeepTogether:
    columns = 2 if two_signatures else 1
    rows = [
        [Paragraph("<br/><br/>__________________________________", styles["body"]) for _ in range(columns)],
        [Paragraph("Navn: ____________________________", styles["small"]) for _ in range(columns)],
        [Paragraph("Dato: _____________________________", styles["small"]) for _ in range(columns)],
    ]
    table = Table(rows, colWidths=[85 * mm] * columns, hAlign="LEFT")
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("RIGHTPADDING", (0, 0), (-1, -1), 12)]))
    return KeepTogether([Paragraph(escape(label), styles["small"]), table])


def _footer(canvas, document) -> None:  # type: ignore[no-untyped-def]
    canvas.saveState()
    width, _height = A4
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, 15 * mm, width - 20 * mm, 15 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 10 * mm, "Talli - usignert utkast, må kontrolleres før bruk")
    canvas.drawRightString(width - 20 * mm, 10 * mm, f"Side {document.page}")
    canvas.restoreState()


def _money(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"))
    whole, decimals = f"{quantized:.2f}".split(".")
    grouped = f"{int(whole):,}".replace(",", " ")
    return f"kr {grouped},{decimals}"


def _number(value: Decimal) -> str:
    if value == value.to_integral_value():
        return f"{int(value):,}".replace(",", " ")
    return f"{value.normalize():f}".replace(".", ",")


def _date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _org_number(value: str) -> str:
    return f"{value[:3]} {value[3:6]} {value[6:]}"
