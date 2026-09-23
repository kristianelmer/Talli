from __future__ import annotations

from xml.etree import ElementTree as ET

from .public import (
    Rf1086DocumentSet,
    Rf1086CashIssueEvent as CashIssueEvent,
    Rf1086CashNominalIncreaseEvent as CashNominalIncreaseEvent,
    Rf1086LossCoveringReductionEvent as LossCoveringReductionEvent,
    Rf1086DividendEvent as DividendEvent,
    Rf1086Case as FilingCase,
    Rf1086FormationEvent as FormationEvent,
    Rf1086ShareSaleEvent as ShareSaleEvent,
    Rf1086Shareholder as Shareholder,
    Rf1086ShareholderKind as ShareholderKind,
    Rf1086ShareholderSnapshot as ShareholderSnapshot,
)
from .readiness import assess_rf1086_readiness, format_readiness_report
from .codes import (
    ACQUISITION_PURCHASE_CODE,
    CASH_NEW_ISSUE_CODE,
    CASH_NOMINAL_INCREASE_CODE,
    DISPOSAL_SALE_CODE,
    DIVIDEND_DISTRIBUTION_CODE,
    FORMATION_STIFTELSE_CODE,
)

SKATTEETATEN_ETAT_ID = "974761076"


def generate_rf1086(case: FilingCase) -> Rf1086DocumentSet:
    from .readiness import validate_capital_case
    validate_capital_case(case)
    return Rf1086DocumentSet(
        hovedskjema_xml=_xml_to_string(_build_hovedskjema(case)),
        underskjema_xml={
            snapshot.shareholder_id: _xml_to_string(_build_underskjema(case, snapshot))
            for snapshot in case.shareholder_snapshots
        },
    )


def filing_preview(case: FilingCase) -> str:
    lines = [
        f"Aksjonærregisteroppgaven {case.company.income_year}",
        f"Selskap: {case.company.name} ({case.company.org_number})",
        f"Aksjeklasse: ordinære ({case.company.share_type})",
        "",
        "Selskapsnivå:",
        f"- Aksjekapital 1. januar: {_amount(case.share_snapshot.previous_share_capital)}",
        f"- Aksjekapital 31. desember: {_amount(case.share_snapshot.current_share_capital)}",
        f"- Antall aksjer 1. januar: {case.share_snapshot.previous_share_count}",
        f"- Antall aksjer 31. desember: {case.share_snapshot.current_share_count}",
        "",
        "Aksjonærer:",
    ]
    shareholders_by_id = {shareholder.id: shareholder for shareholder in case.shareholders}
    for snapshot in case.shareholder_snapshots:
        shareholder = shareholders_by_id[snapshot.shareholder_id]
        lines.append(
            f"- {shareholder.name}: {snapshot.previous_share_count} aksjer 1. januar, "
            f"{snapshot.current_share_count} aksjer 31. desember"
        )

    if case.events:
        lines.extend(["", "Hendelser:"])
        for event in case.events:
            if isinstance(event, (FormationEvent, CashIssueEvent)):
                lines.append(
                    f"- {'Nyemisjon (kontant)' if isinstance(event, CashIssueEvent) else 'Stiftelse/utstedelse'} {event.timestamp.isoformat()}: "
                    f"{event.issued_share_count} aksjer, pålydende {_amount(event.nominal_value)}, "
                    f"{len(event.allocations)} aksjonær(er)"
                )
            elif isinstance(event, CashNominalIncreaseEvent):
                lines.append(f"- Kontant kapitalforhøyelse ved økning av pålydende {event.timestamp.isoformat()}: "
                    f"aksjekapital {_amount(event.capital_increase)}, overkurs {_amount(event.premium)}")
            elif isinstance(event, LossCoveringReductionEvent):
                lines.append(f"- Registrert kapitalnedsettelse til dekning av tap {event.timestamp.isoformat()}: "
                    f"{_amount(event.capital_reduction)}, uten utbetaling til aksjonærene")
            elif isinstance(event, ShareSaleEvent):
                seller = shareholders_by_id[event.seller_shareholder_id].name
                buyer = shareholders_by_id[event.buyer_shareholder_id].name
                lines.append(
                    f"- Aksjesalg {event.timestamp.isoformat()}: {event.share_count} aksjer "
                    f"fra {seller} til {buyer}, vederlag {_amount(event.consideration)}"
                )
            elif isinstance(event, DividendEvent):
                lines.append(
                    f"- Utbytte {event.timestamp.isoformat()}: totalt {_amount(event.total_amount)}, "
                    f"{_amount(event.per_share_amount)} per aksje"
                )
    return "\n".join(lines) + "\n"


def readiness_report(case: FilingCase) -> str:
    return format_readiness_report(assess_rf1086_readiness(case))


def _build_hovedskjema(case: FilingCase) -> ET.Element:
    root = ET.Element(
        "Skjema",
        {
            "skjemanummer": "890",
            "spesifikasjonsnummer": "12144",
            "blankettnummer": "RF-1086",
            "tittel": "Aksjonærregisteroppgaven",
            "gruppeid": "2586",
            "etatid": SKATTEETATEN_ETAT_ID,
        },
    )

    general = _group(root, "GenerellInformasjon-grp-2587", "2587")
    company = _group(general, "Selskap-grp-2588", "2588")
    _data(company, "EnhetOrganisasjonsnummer-datadef-18", "18", case.company.org_number)
    _data(company, "EnhetNavn-datadef-1", "1", case.company.name)
    _data(company, "EnhetAdresse-datadef-15", "15", case.company.address)
    _data(company, "EnhetPostnummer-datadef-6673", "6673", case.company.postal_code)
    _data(company, "EnhetPoststed-datadef-6674", "6674", case.company.city)
    _data(company, "AksjeType-datadef-17659", "17659", case.company.share_type)
    _data(company, "Inntektsar-datadef-692", "692", case.company.income_year)
    contact = _group(general, "Kontaktperson-grp-3442", "3442")
    if case.company.contact_email:
        _data(contact, "KontaktpersonSkjemaEPost-datadef-30533", "30533", case.company.contact_email)
    _group(general, "AnnenKontaktperson-grp-5384", "5384")

    info = _group(root, "Selskapsopplysninger-grp-2589", "2589")
    _pair_group(
        info,
        "AksjekapitalForHeleSelskapet-grp-3443",
        "3443",
        ("AksjekapitalFjoraret-datadef-7129", "7129", case.share_snapshot.previous_share_capital),
        ("Aksjekapital-datadef-87", "87", case.share_snapshot.current_share_capital),
    )
    _pair_group(
        info,
        "AksjekapitalIDenneAksjeklassen-grp-3444",
        "3444",
        ("AksjekapitalISINAksjetypeFjoraret-datadef-17663", "17663", case.share_snapshot.previous_share_capital),
        ("AksjekapitalISINAksjetype-datadef-17664", "17664", case.share_snapshot.current_share_capital),
    )
    _pair_group(
        info,
        "PalydendePerAksje-grp-3447",
        "3447",
        ("AksjeMvPalydendeFjoraret-datadef-23944", "23944", case.share_snapshot.previous_nominal_value),
        ("AksjeMvPalydende-datadef-23945", "23945", case.share_snapshot.current_nominal_value),
    )
    _pair_group(
        info,
        "AntallAksjerIDenneAksjeklassen-grp-3445",
        "3445",
        ("AksjerMvAntallFjoraret-datadef-29166", "29166", case.share_snapshot.previous_share_count),
        ("AksjerMvAntall-datadef-29167", "29167", case.share_snapshot.current_share_count),
    )
    _pair_group(
        info,
        "InnbetaltAksjekapitalIDenneAksjeklassen-grp-3446",
        "3446",
        ("AksjekapitalInnbetaltFjoraret-datadef-8020", "8020", case.share_snapshot.previous_paid_in_share_capital),
        ("AksjekapitalInnbetalt-datadef-5867", "5867", case.share_snapshot.current_paid_in_share_capital),
    )
    _pair_group(
        info,
        "InnbetaltOverkursIDenneAksjeklassen-grp-3448",
        "3448",
        ("AksjeOverkursISINAksjetypeFjoraret-datadef-17662", "17662", case.share_snapshot.previous_paid_in_premium),
        ("AksjeOverkursISINAksjetype-datadef-17661", "17661", case.share_snapshot.current_paid_in_premium),
    )

    dividend_events = [event for event in case.events if isinstance(event, DividendEvent)]
    if dividend_events:
        dividends = _group(root, "Utbytte-grp-3449", "3449")
        for event in dividend_events:
            event_group = _group(dividends, "UtdeltSkatterettsligUtbytteILopetAvInntektsaret-grp-3451", "3451")
            _data(event_group, "AksjeUtbytteISINAksjetype-datadef-17665", "17665", event.total_amount)
            _data(event_group, "AksjeUtbyttePerAksje-datadef-23946", "23946", event.per_share_amount)
            _data(event_group, "AksjeUtbytteHendelsestype-datadef-36564", "36564", DIVIDEND_DISTRIBUTION_CODE)
            _data(event_group, "AksjeUtbytteTidspunkt-datadef-17667", "17667", _dt(event.timestamp))

    formation_events = [event for event in case.events if isinstance(event, (FormationEvent, CashIssueEvent))]
    if formation_events:
        issuances = _group(root, "UtstedelseAvAksjerIfmStiftelseNyemisjonMv-grp-3452", "3452")
        for event in formation_events:
            issue = _group(issuances, "AntallNyutstedteAksjer-grp-3453", "3453")
            _data(issue, "AksjerNyutstedteStiftelseMvAntall-datadef-17668", "17668", event.issued_share_count)
            _data(issue, "AksjerStiftelseMvAntall-datadef-17669", "17669", event.share_count_after)
            _data(issue, "AksjerNyutstedteStiftelseMvType-datadef-17670", "17670", CASH_NEW_ISSUE_CODE if isinstance(event, CashIssueEvent) else FORMATION_STIFTELSE_CODE)
            _data(issue, "AksjerNyutstedteStiftelseMvTidspunkt-datadef-17671", "17671", _dt(event.timestamp))
            _data(issue, "AksjerNyutstedteStiftelseMvPalydende-datadef-23947", "23947", event.nominal_value)
            _data(issue, "AksjerNyutstedteStiftelseMvOverkurs-datadef-23948", "23948", event.premium)

    changes = None
    # XSD orders post 15 before post 16, irrespective of event chronology.
    for event_class in (CashNominalIncreaseEvent, LossCoveringReductionEvent):
        for event in case.events:
            if not isinstance(event, event_class):
                continue
            if changes is None:
                changes = _group(root, "EndringerIAksjekapitalOgOverkurs-grp-3460", "3460")
            if isinstance(event, CashNominalIncreaseEvent):
                change = _group(changes, "ForhoyelseAvAKVedOkningAvPalydende-grp-3463", "3463")
                _data(change, "AksjekapitalNyemisjonForhoyelse-datadef-17713", "17713", event.capital_increase)
                _data(change, "AksjeNyemisjonPalydendeForhoyelse-datadef-23958", "23958", event.nominal_value_increase)
                _data(change, "AksjePalydendeEtterNyemisjon-datadef-23959", "23959", event.nominal_value_after)
                _data(change, "AksjekapitalForhoyelsePalydendeHendelsestype-datadef-28268", "28268", CASH_NOMINAL_INCREASE_CODE)
                _data(change, "AksjeNyemisjonTidspunkt-datadef-17716", "17716", _dt(event.timestamp))
                _data(change, "AksjeOverkursForhoyelse-datadef-22071", "22071", event.premium)
            else:
                change = _group(changes, "NedsettelseAvInnbetaltOgFondsemittertAK-grp-3464", "3464")
                _data(change, "AksjekapitalInnbetaltNedsettelse-datadef-17717", "17717", event.capital_reduction)
                _data(change, "AksjePalydendeNedsettelseTapsdekning-datadef-23960", "23960", event.nominal_value_reduction)
                _data(change, "AksjePalydendeEtterNedsettelseTapsdekning-datadef-23961", "23961", event.nominal_value_after)
                _data(change, "AksjeNedsettelseTidspunkt-datadef-17720", "17720", _dt(event.timestamp))
                _data(change, "AksjekapitalFondsemittertNedsettelse-datadef-17721", "17721", 0)

    return root


def _build_underskjema(case: FilingCase, snapshot: ShareholderSnapshot) -> ET.Element:
    shareholder = next(item for item in case.shareholders if item.id == snapshot.shareholder_id)
    root = ET.Element(
        "Skjema",
        {
            "skjemanummer": "923",
            "spesifikasjonsnummer": "12232",
            "blankettnummer": "RF-1086-U",
            "tittel": "Aksjonærregisteroppgaven - underskjema",
            "gruppeid": "3983",
            "etatid": SKATTEETATEN_ETAT_ID,
        },
    )

    identities = _group(root, "SelskapsOgAksjonaropplysninger-grp-3987", "3987")
    company_id = _group(identities, "Selskapsidentifikasjon-grp-3986", "3986")
    _data(company_id, "EnhetOrganisasjonsnummer-datadef-18", "18", case.company.org_number)
    _data(company_id, "AksjeType-datadef-17659", "17659", case.company.share_type)
    _data(company_id, "Inntektsar-datadef-692", "692", case.company.income_year)

    shareholder_group = _group(identities, "NorskUtenlandskAksjonar-grp-3988", "3988")
    if shareholder.kind == ShareholderKind.NORWEGIAN_PERSON:
        _data(shareholder_group, "AksjonarFodselsnummer-datadef-1156", "1156", shareholder.national_id)
    else:
        _data(shareholder_group, "AksjonarOrganisasjonsnummer-datadef-7597", "7597", shareholder.org_number)
    _data(shareholder_group, "AksjonarNavn-datadef-1153", "1153", shareholder.name)
    _group(shareholder_group, "Adresse-grp-7722", "7722")

    holding = _group(root, "AntallAksjerUtbytteOgTilbakebetalingAvTidligereInnbetaltKapit-grp-3990", "3990")
    count_group = _group(holding, "AntallAksjerPerAksjonar-grp-3989", "3989")
    _data(count_group, "AksjerAntallFjoraret-datadef-29168", "29168", snapshot.previous_share_count)
    _data(count_group, "AksjonarAksjerAntall-datadef-17741", "17741", snapshot.current_share_count)

    for event in case.events:
        if isinstance(event, DividendEvent):
            for allocation in event.allocations:
                if allocation.shareholder_id == shareholder.id:
                    dividend = _group(holding, "UtdeltUtbyttePerAksjonar-grp-3991", "3991")
                    _data(dividend, "Aksjeutbytte-datadef-29169", "29169", allocation.amount)
                    _data(dividend, "AksjerUtbytteAntall-datadef-17742", "17742", allocation.share_count_basis)
                    _data(dividend, "AksjerUtbytteTidspunkt-datadef-17769", "17769", _dt(event.timestamp))
                    _data(dividend, "AutomatiskMotregningOnskerIkke-datadef-37159", "37159", 0)

    acquisitions = [
        event for event in case.events if _shareholder_has_acquisition(event, shareholder.id)
    ]
    if acquisitions:
        transactions = _group(root, "Transaksjoner-grp-3992", "3992")
        acquisition_parent = _group(transactions, "KjopArvGaveStiftelseNyemisjonMv-grp-3993", "3993")
        for event in acquisitions:
            acquisition = _group(acquisition_parent, "AntallAksjerITilgang-grp-3998", "3998")
            if isinstance(event, (FormationEvent, CashIssueEvent)):
                allocation = next(item for item in event.allocations if item.shareholder_id == shareholder.id)
                amount = allocation.share_count
                value = allocation.acquisition_value
                event_type = CASH_NEW_ISSUE_CODE if isinstance(event, CashIssueEvent) else FORMATION_STIFTELSE_CODE
            else:
                amount = event.share_count
                value = event.consideration
                event_type = ACQUISITION_PURCHASE_CODE
            _data(acquisition, "AksjerKjopAntall-datadef-12153", "12153", amount)
            _data(acquisition, "AksjeErvervType-datadef-17745", "17745", event_type)
            _data(acquisition, "AksjerErvervsdato-datadef-17746", "17746", _dt(event.timestamp))
            _data(acquisition, "AksjeAnskaffelsesverdi-datadef-17636", "17636", value)
            if isinstance(event, ShareSaleEvent):
                seller = next(item for item in case.shareholders if item.id == event.seller_shareholder_id)
                if seller.kind == ShareholderKind.NORWEGIAN_PERSON:
                    _data(acquisition, "AksjonarTidligereFodselsnummer-datadef-26530", "26530", seller.national_id)
                else:
                    _data(acquisition, "AksjonarTidligereOrganisasjonsnummer-datadef-26531", "26531", seller.org_number)

    disposals = [event for event in case.events if isinstance(event, ShareSaleEvent) and event.seller_shareholder_id == shareholder.id]
    if disposals:
        sales = _group(root, "SalgArvGaveLikvidasjonPartiellLikvidasjonMv-grp-3995", "3995")
        for event in disposals:
            disposal = _group(sales, "AksjerIAvgang-grp-4002", "4002")
            _data(disposal, "AksjerArvMvOmsattAntall-datadef-17752", "17752", event.share_count)
            _data(disposal, "AksjerArvMvOmsattType-datadef-17753", "17753", DISPOSAL_SALE_CODE)
            _data(disposal, "AksjerArvMvOmsattTidspunkt-datadef-17754", "17754", _dt(event.timestamp))
            _data(disposal, "AksjerArvMvOmsatt-datadef-17755", "17755", event.consideration)
            buyer = next(item for item in case.shareholders if item.id == event.buyer_shareholder_id)
            if buyer.kind == ShareholderKind.NORWEGIAN_PERSON:
                _data(disposal, "AksjonarOvertakendeFodselsnummer-datadef-26532", "26532", buyer.national_id)
            else:
                _data(disposal, "AksjonarOvertakendeOrganisasjonsnummer-datadef-26533", "26533", buyer.org_number)

    changes = None
    for event in case.events:
        if isinstance(event, CashNominalIncreaseEvent):
            for allocation in event.allocations:
                if allocation.shareholder_id != shareholder.id:
                    continue
                if changes is None:
                    changes = _group(root, "EndringerIAksjekapitalOgOverkurs-grp-3997", "3997")
                change = _group(changes, "ForhoyelseAvInnbetaltAksjekapitalVedOkning-grp-4987", "4987")
                _data(change, "AksjekapitalNyemisjonForhoyelseAksjonar-datadef-22073", "22073", allocation.capital_increase)
                _data(change, "AksjeOverkursForhoyelseAksjonar-datadef-22076", "22076", allocation.premium)
                _data(change, "AksjeNyemisjonPalydendeForhoyelseAksjonar-datadef-23971", "23971", event.nominal_value_increase)
                _data(change, "AksjekapitalNyemisjonForhoyelsePalydendeTransaksjonstype-datadef-28267", "28267", CASH_NOMINAL_INCREASE_CODE)
                _data(change, "AksjeNyemisjonTidspunktAksjonar-datadef-22075", "22075", _dt(event.timestamp))

    return root


def _shareholder_has_acquisition(event: FormationEvent | CashIssueEvent | CashNominalIncreaseEvent | LossCoveringReductionEvent | ShareSaleEvent | DividendEvent, shareholder_id: str) -> bool:
    if isinstance(event, (FormationEvent, CashIssueEvent)):
        return any(allocation.shareholder_id == shareholder_id for allocation in event.allocations)
    if isinstance(event, ShareSaleEvent):
        return event.buyer_shareholder_id == shareholder_id
    return False


def _pair_group(parent: ET.Element, name: str, group_id: str, previous: tuple[str, str, object], current: tuple[str, str, object]) -> None:
    group = _group(parent, name, group_id)
    _data(group, previous[0], previous[1], previous[2])
    _data(group, current[0], current[1], current[2])


def _group(parent: ET.Element, name: str, group_id: str) -> ET.Element:
    return ET.SubElement(parent, name, {"gruppeid": group_id})


def _data(parent: ET.Element, name: str, orid: str, value: object) -> ET.Element:
    element = ET.SubElement(parent, name, {"orid": orid})
    element.text = _value(value)
    return element


def _value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _amount(value: float) -> str:
    from decimal import Decimal
    # Filing amounts may have more than two decimal places. Preserve those
    # digits and avoid ambient rounding or a lossy float conversion in review.
    whole, _, fraction = format(Decimal(str(value)), "f").partition(".")
    fraction = fraction.rstrip("0")
    return (whole + "." + fraction.ljust(2, "0") if fraction else whole) + " kr"


def _dt(value) -> str:
    return value.replace(microsecond=0).isoformat()


def _xml_to_string(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def render_rf1086_preview(case: FilingCase):
    from .public import Rf1086RenderedPreview
    readiness = assess_rf1086_readiness(case)
    if any(issue.code == "capital_event_reconciliation" for issue in readiness.issues):
        return Rf1086RenderedPreview(readiness.filing, readiness.status, readiness.issues,
            "RF-1086 kapitalhendelser kunne ikke avstemmes.\n")
    documents = generate_rf1086(case)
    return Rf1086RenderedPreview(readiness.filing, readiness.status, readiness.issues,
        filing_preview(case), documents.hovedskjema_xml, documents.underskjema_xml)


def _invalid_no_activity_case(value) -> str | None:
    import math
    import re
    company = value['company']; shares = value['share_snapshot']
    holders = value['shareholders']; snapshots = value['shareholder_snapshots']
    integer = lambda number: type(number) in (int, float) and math.isfinite(number) and int(number) == number
    digits = lambda text, count: isinstance(text, str) and re.fullmatch('[0-9]{'+str(count)+'}', text) is not None
    if not value['case_id']: return 'case_id is required'
    if not digits(company['org_number'], 9): return 'company org_number must contain 9 digits'
    if not digits(company['postal_code'], 4): return 'company postal_code must contain 4 digits'
    if not integer(company['income_year']) or not 2000 <= company['income_year'] <= 2100:
        return 'company income_year must be between 2000 and 2100'
    if company['share_type'] != '01': return 'only ordinary share class 01 is supported'
    if value['events']: return 'the serverless RF-1086 renderer only accepts no-activity cases'
    if not holders: return 'at least one shareholder is required'
    numeric_names = ('previous_share_capital','current_share_capital','previous_nominal_value','current_nominal_value',
        'previous_share_count','current_share_count','previous_paid_in_share_capital','current_paid_in_share_capital',
        'previous_paid_in_premium','current_paid_in_premium')
    if any(type(shares[name]) not in (int, float) or not math.isfinite(shares[name]) or shares[name] < 0 for name in numeric_names):
        return 'share snapshot values must be non-negative numbers'
    if not all(integer(shares[name]) for name in ('previous_share_count', 'current_share_count')):
        return 'share counts must be integers'
    holder_ids = {holder['id'] for holder in holders}; snapshot_ids = {snapshot['shareholder_id'] for snapshot in snapshots}
    if len(holder_ids) != len(holders) or len(snapshot_ids) != len(snapshots) or holder_ids != snapshot_ids:
        return 'shareholders and shareholder snapshots must contain the same unique ids'
    for holder in holders:
        if not holder['id'] or not holder['name']: return 'shareholder id and name are required'
        if holder['kind'] not in ('norwegian_person', 'norwegian_company'):
            return 'shareholder kind must be norwegian_person or norwegian_company'
        if holder['kind'] == 'norwegian_person' and not digits(holder.get('national_id'), 11):
            return 'Norwegian personal shareholder requires an 11 digit national_id'
        if holder['kind'] == 'norwegian_company' and not digits(holder.get('org_number'), 9):
            return 'Norwegian corporate shareholder requires a 9 digit org_number'
    if any(not integer(snapshot[name]) or snapshot[name] < 0 for snapshot in snapshots
        for name in ('previous_share_count', 'current_share_count')):
        return 'shareholder share counts must be non-negative integers'
    for period in ('previous','current'):
        if sum(snapshot[period+'_share_count'] for snapshot in snapshots) != shares[period+'_share_count']:
            return 'sum of '+period+' shareholder shares must equal company '+period+' share count'
    return None


def _case_values(case):
    from collections.abc import Mapping
    from dataclasses import fields, is_dataclass
    if is_dataclass(case):
        return {item.name: _case_values(getattr(case, item.name)) for item in fields(case)}
    if isinstance(case, Mapping): return {key: _case_values(value) for key, value in case.items()}
    if isinstance(case, (list, tuple)): return [_case_values(item) for item in case]
    return case


def _javascript_fixed(value: float, places: int) -> str:
    # Number.toFixed rounds the exact binary64 value, ties away from zero.
    from decimal import Decimal, ROUND_HALF_UP, localcontext
    with localcontext() as context:
        context.prec = 400
        return format(Decimal.from_float(float(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP), 'f')


def _web_xml(root: ET.Element) -> str:
    # Reuse the canonical RF element construction. The deployed serializer's
    # empty text nodes are explicit pairs; empty groups remain self-closing.
    def escape(value): return value.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
    def visit(element, depth=0):
        indent = '  '*depth
        attributes = ''.join(' '+key+'="'+escape(value).replace('"','&quot;')+'"' for key,value in element.attrib.items())
        if len(element):
            return '\n'.join([indent+'<'+element.tag+attributes+'>',*(visit(child,depth+1) for child in element),indent+'</'+element.tag+'>'])
        if element.text is None: return indent+'<'+element.tag+attributes+' />'
        return indent+'<'+element.tag+attributes+'>'+escape(element.text)+'</'+element.tag+'>'
    return '<?xml version="1.0" encoding="UTF-8"?>\n'+visit(root)+'\n'


def render_no_activity_rf1086_preview(value):
    from .public import Rf1086RenderedPreview, Rf1086ReadinessIssue
    from .case_parser import parse_rf1086_case
    raw = _case_values(value)
    invalid = _invalid_no_activity_case(raw)
    if invalid:
        return Rf1086RenderedPreview('aksjonærregisteroppgaven','blocked',
            (Rf1086ReadinessIssue('error','invalid_case',invalid),),f'RF-1086 kunne ikke genereres: {invalid}\n')
    # The no-activity entry never renders an optional contact email; retain the
    # original deployed shape independently of the offline parser's defaults.
    raw['company'].pop('contact_email', None)
    try:
        case = parse_rf1086_case(raw)
    except ValueError:
        return Rf1086RenderedPreview('aksjonærregisteroppgaven', 'blocked',
            (Rf1086ReadinessIssue('error', 'capital_event_reconciliation',
                'Opplysninger om aksjer og kapital kan ikke avstemmes.'),),
            'RF-1086 kunne ikke genereres: Opplysninger om aksjer og kapital kan ikke avstemmes.\n')
    main = _build_hovedskjema(case)
    sub = {snapshot.shareholder_id: _build_underskjema(case,snapshot) for snapshot in case.shareholder_snapshots}
    # Rendered numeric fields that can be fractional use the original JS
    # decimal rule. Replacing their text leaves one canonical element layout.
    numeric = {
        '7129':'previous_share_capital','87':'current_share_capital',
        '17663':'previous_share_capital','17664':'current_share_capital',
        '23944':'previous_nominal_value','23945':'current_nominal_value',
        '8020':'previous_paid_in_share_capital','5867':'current_paid_in_share_capital',
        '17662':'previous_paid_in_premium','17661':'current_paid_in_premium',
    }
    for element in main.iter():
        name = numeric.get(element.get('orid'))
        if name:
            number = getattr(case.share_snapshot,name)
            element.text = str(int(number)) if float(number).is_integer() else _javascript_fixed(number,6).rstrip('0').rstrip('.')
    preview = filing_preview(case)
    for name in ('previous_share_capital','current_share_capital'):
        number = getattr(case.share_snapshot,name)
        if not float(number).is_integer(): preview = preview.replace(_amount(number), _javascript_fixed(number,2)+' kr')
    return Rf1086RenderedPreview('aksjonærregisteroppgaven','ready',(),preview,
        _web_xml(main),{name:_web_xml(root) for name,root in sub.items()})



def build_no_activity_rf1086_case(*, company, opening):
    import re
    from .public import (Rf1086Case, Rf1086Company, Rf1086ShareSnapshot, Rf1086Shareholder,
        Rf1086ShareholderSnapshot, ShareholderRegisterFilingError)
    if company.company_id != opening.company_id:
        raise ShareholderRegisterFilingError.not_found()
    if not company.postal_code or re.fullmatch('[0-9]{4}',company.postal_code) is None or not opening.shareholders:
        raise ShareholderRegisterFilingError.invalid_input()
    return Rf1086Case(f'persisted-{company.org_number}-{opening.income_year.value}-{opening.opening_snapshot_id}',
        Rf1086Company(company.org_number,company.name,company.address or 'Ukjent adresse',company.postal_code,
            company.city or 'Ukjent',opening.income_year.value,'01'),
        Rf1086ShareSnapshot(float(opening.share_capital),float(opening.share_capital),float(opening.nominal_value),float(opening.nominal_value),
            opening.share_count,opening.share_count,float(opening.share_capital),float(opening.share_capital),0,0),
        tuple(Rf1086Shareholder(holder.id,holder.kind,holder.name,holder.national_id,holder.org_number) for holder in opening.shareholders),
        tuple(Rf1086ShareholderSnapshot(holder.id,holder.share_count,holder.share_count) for holder in opening.shareholders),())
