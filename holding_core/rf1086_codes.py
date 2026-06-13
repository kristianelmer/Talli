from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class CodeVerificationStatus(StrEnum):
    OFFICIAL_API_EXAMPLE = "official_api_example"
    PUBLIC_LABEL_ONLY = "public_label_only"


class Rf1086CodeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: str
    field_name: str
    code_value: str
    public_label: str
    verification_status: CodeVerificationStatus
    production_blocker: bool
    authority_note: str
    sources: tuple[str, ...]


FORMATION_STIFTELSE_CODE = "N"
ACQUISITION_PURCHASE_CODE = "K"
DISPOSAL_SALE_CODE = "S"
DIVIDEND_DISTRIBUTION_CODE = "U"

RF1086_CODE_DECISIONS: tuple[Rf1086CodeDecision, ...] = (
    Rf1086CodeDecision(
        event="stiftelse",
        field_name="AksjerNyutstedteStiftelseMvType-datadef-17670 / AksjeErvervType-datadef-17745",
        code_value=FORMATION_STIFTELSE_CODE,
        public_label="stiftelse",
        verification_status=CodeVerificationStatus.OFFICIAL_API_EXAMPLE,
        production_blocker=False,
        authority_note="Observed in Skatteetaten's public API example for RF-1086/RF-1086-U.",
        sources=(
            "https://skatteetaten.github.io/api-dokumentasjon/api/innrapportering-aksjonaerregisteroppgave",
        ),
    ),
    Rf1086CodeDecision(
        event="kjop",
        field_name="AksjeErvervType-datadef-17745",
        code_value=ACQUISITION_PURCHASE_CODE,
        public_label="kjøp",
        verification_status=CodeVerificationStatus.PUBLIC_LABEL_ONLY,
        production_blocker=True,
        authority_note=(
            "Skatteetaten public examples document the purchase label and reporting position, "
            "but the local XSD leaves the field as free text and does not verify the K code value."
        ),
        sources=(
            "https://www.skatteetaten.no/bedrift-og-organisasjon/rapportering-og-bransjer/aksjonarregisteroppgaven/eksempler-pa-utfylling-av-aksjonarregisteroppgaven/",
        ),
    ),
    Rf1086CodeDecision(
        event="salg",
        field_name="AksjerArvMvOmsattType-datadef-17753",
        code_value=DISPOSAL_SALE_CODE,
        public_label="salg",
        verification_status=CodeVerificationStatus.PUBLIC_LABEL_ONLY,
        production_blocker=True,
        authority_note=(
            "Skatteetaten public examples document the sale label and reporting position, "
            "but the local XSD leaves the field as free text and does not verify the S code value."
        ),
        sources=(
            "https://www.skatteetaten.no/bedrift-og-organisasjon/rapportering-og-bransjer/aksjonarregisteroppgaven/eksempler-pa-utfylling-av-aksjonarregisteroppgaven/",
        ),
    ),
    Rf1086CodeDecision(
        event="utbytte",
        field_name="AksjeUtbytteHendelsestype-datadef-36564",
        code_value=DIVIDEND_DISTRIBUTION_CODE,
        public_label="utbytte",
        verification_status=CodeVerificationStatus.PUBLIC_LABEL_ONLY,
        production_blocker=True,
        authority_note=(
            "Dividend event type is accepted by local XSD shape, but public sources reviewed do not verify "
            "the U code value for production direct filing."
        ),
        sources=("docs/filing/aksjonaerregisteroppgaveHovedskjema.xsd",),
    ),
)


def rf1086_code_decisions() -> tuple[Rf1086CodeDecision, ...]:
    return RF1086_CODE_DECISIONS


def production_code_blockers() -> tuple[Rf1086CodeDecision, ...]:
    return tuple(decision for decision in RF1086_CODE_DECISIONS if decision.production_blocker)
