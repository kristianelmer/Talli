from __future__ import annotations

from .public import Rf1086CodeVerificationStatus as CodeVerificationStatus, Rf1086CodeDecision

from .public import Rf1086DividendEvent as DividendEvent, Rf1086Case as FilingCase, Rf1086FormationEvent as FormationEvent, Rf1086ShareSaleEvent as ShareSaleEvent
from .public import Rf1086CashIssueEvent as CashIssueEvent, Rf1086CashNominalIncreaseEvent as CashNominalIncreaseEvent


# Labelled first-party SBS examples, verified 2026-09-17. The older API
# transport example's N was incorrectly inferred to mean formation.
FORMATION_STIFTELSE_CODE = "T"
ACQUISITION_PURCHASE_CODE = "K"
DISPOSAL_SALE_CODE = "R"
DIVIDEND_DISTRIBUTION_CODE = "Y"
CASH_NEW_ISSUE_CODE = "N"
CASH_NOMINAL_INCREASE_CODE = "6"

_SBS = "https://www.skatteetaten.no/contentassets/050b9c39dcdd460d91a2addaf67a6eeb/"
_DESIGN = "https://www.skatteetaten.no/contentassets/d70d335c2a024f7ea7eb421fc53f4ec7/rf-1086_detaljert_design_2024.xlsx"

RF1086_CODE_DECISIONS: tuple[Rf1086CodeDecision, ...] = tuple(
    Rf1086CodeDecision(
        event=event,
        field_name=field_name,
        code_value=code,
        public_label=label,
        verification_status=CodeVerificationStatus.VERIFIED,
        production_blocker=False,
        authority_note=(
            "Meaning established by labelled Skatteetaten SBS examples or detailed design and value admitted by "
            "the current official XSD. This is mapping evidence, not TT02 or production acceptance."
        ),
        sources=tuple(name if name.startswith('https://') else _SBS + name for name in examples),
    )
    for event, field_name, code, label, examples in (
        ("stiftelse", "AksjerNyutstedteStiftelseMvType-datadef-17670 / AksjeErvervType-datadef-17745",
         FORMATION_STIFTELSE_CODE, "stiftelse",
         ("stiftelseavselskap_hovedskjema.txt", "stiftelseavselskap_underskjema.txt")),
        ("kjop", "AksjeErvervType-datadef-17745", ACQUISITION_PURCHASE_CODE, "kjøp",
         ("kjopogsalg_underskjema_to.txt",)),
        ("salg", "AksjerArvMvOmsattType-datadef-17753", DISPOSAL_SALE_CODE, "salg",
         ("kjopogsalg_underskjema_en.txt",)),
        ("utbytte", "AksjeUtbytteHendelsestype-datadef-36564", DIVIDEND_DISTRIBUTION_CODE, "utbytte",
         ("utbytte_hovedskjema.txt",)),
        ("cash_issue", "AksjerNyutstedteStiftelseMvType-datadef-17670 / AksjeErvervType-datadef-17745",
         CASH_NEW_ISSUE_CODE, "nyemisjon (kontant)", (_DESIGN,)),
        ("cash_nominal_increase", "AksjekapitalForhoyelsePalydendeHendelsestype-datadef-28268 / AksjekapitalNyemisjonForhoyelsePalydendeTransaksjonstype-datadef-28267",
         CASH_NOMINAL_INCREASE_CODE, "forhøyelse av pålydende (kontant)", ("nyemisjon_hovedskjema.txt", _DESIGN)),
    )
)


def rf1086_code_decisions() -> tuple[Rf1086CodeDecision, ...]:
    return RF1086_CODE_DECISIONS


def production_code_blockers() -> tuple[Rf1086CodeDecision, ...]:
    return tuple(decision for decision in RF1086_CODE_DECISIONS if decision.production_blocker)


def production_scope_exclusions() -> tuple[Rf1086CodeDecision, ...]:
    return tuple(
        decision
        for decision in RF1086_CODE_DECISIONS
        if decision.verification_status == CodeVerificationStatus.EXCLUDED_FROM_LIVE_SCOPE
    )


def rf1086_code_decisions_for_case(case: FilingCase) -> tuple[Rf1086CodeDecision, ...]:
    required_events: list[str] = []
    for event in case.events:
        if isinstance(event, FormationEvent):
            required_events.append("stiftelse")
        elif isinstance(event, ShareSaleEvent):
            required_events.extend(["kjop", "salg"])
        elif isinstance(event, DividendEvent):
            required_events.append("utbytte")
        elif isinstance(event, CashIssueEvent):
            required_events.append("cash_issue")
        elif isinstance(event, CashNominalIncreaseEvent):
            required_events.append("cash_nominal_increase")

    decisions_by_event = {decision.event: decision for decision in RF1086_CODE_DECISIONS}
    ordered_unique_events = tuple(dict.fromkeys(required_events))
    return tuple(decisions_by_event[event] for event in ordered_unique_events)


def production_code_blockers_for_case(case: FilingCase) -> tuple[Rf1086CodeDecision, ...]:
    return tuple(decision for decision in rf1086_code_decisions_for_case(case) if decision.production_blocker)


def production_scope_exclusions_for_case(case: FilingCase) -> tuple[Rf1086CodeDecision, ...]:
    return tuple(
        decision
        for decision in rf1086_code_decisions_for_case(case)
        if decision.verification_status == CodeVerificationStatus.EXCLUDED_FROM_LIVE_SCOPE
    )


def assert_rf1086_production_codes_verified(case: FilingCase) -> None:
    blockers = production_code_blockers_for_case(case)
    if blockers:
        blocked = ", ".join(f"{decision.event}={decision.code_value}" for decision in blockers)
        raise ValueError(f"RF-1086 production code values are not verified: {blocked}")
