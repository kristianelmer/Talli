from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from holding_core.models import (
    DividendEvent,
    FilingCase,
    FormationEvent,
    ShareSaleEvent,
    Shareholder,
    ShareholderKind,
    ShareholderSnapshot,
)
from holding_core.readiness import assess_rf1086_readiness, format_readiness_report

SKATTEETATEN_ETAT_ID = "974761076"


@dataclass(frozen=True)
class Rf1086DocumentSet:
    hovedskjema_xml: str
    underskjema_xml: dict[str, str]


def generate_rf1086(case: FilingCase) -> Rf1086DocumentSet:
    return Rf1086DocumentSet(
        hovedskjema_xml=_xml_to_string(_build_hovedskjema(case)),
        underskjema_xml={
            snapshot.shareholder_id: _xml_to_string(_build_underskjema(case, snapshot))
            for snapshot in case.shareholder_snapshots
        },
    )


def write_rf1086(case: FilingCase, out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    documents = generate_rf1086(case)
    paths = [out / "1086H.xml"]
    paths[0].write_text(documents.hovedskjema_xml, encoding="utf-8")
    for shareholder_id, xml in documents.underskjema_xml.items():
        path = out / f"1086U-{shareholder_id}.xml"
        path.write_text(xml, encoding="utf-8")
        paths.append(path)
    return paths


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
            if isinstance(event, FormationEvent):
                lines.append(
                    f"- Stiftelse/utstedelse {event.timestamp.isoformat()}: "
                    f"{event.issued_share_count} aksjer, pålydende {_amount(event.nominal_value)}, "
                    f"{len(event.allocations)} aksjonær(er)"
                )
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
            _data(event_group, "AksjeUtbytteISINAksjetype-datadef-17665", "17665", case.company.share_type)
            _data(event_group, "AksjeUtbyttePerAksje-datadef-23946", "23946", event.per_share_amount)
            _data(event_group, "AksjeUtbytteHendelsestype-datadef-36564", "36564", "U")
            _data(event_group, "AksjeUtbytteTidspunkt-datadef-17667", "17667", _dt(event.timestamp))

    formation_events = [event for event in case.events if isinstance(event, FormationEvent)]
    if formation_events:
        issuances = _group(root, "UtstedelseAvAksjerIfmStiftelseNyemisjonMv-grp-3452", "3452")
        for event in formation_events:
            issue = _group(issuances, "AntallNyutstedteAksjer-grp-3453", "3453")
            _data(issue, "AksjerNyutstedteStiftelseMvAntall-datadef-17668", "17668", event.issued_share_count)
            _data(issue, "AksjerStiftelseMvAntall-datadef-17669", "17669", event.share_count_after)
            _data(issue, "AksjerNyutstedteStiftelseMvType-datadef-17670", "17670", "N")
            _data(issue, "AksjerNyutstedteStiftelseMvTidspunkt-datadef-17671", "17671", _dt(event.timestamp))
            _data(issue, "AksjerNyutstedteStiftelseMvPalydende-datadef-23947", "23947", event.nominal_value)
            _data(issue, "AksjerNyutstedteStiftelseMvOverkurs-datadef-23948", "23948", event.premium)

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
            if isinstance(event, FormationEvent):
                allocation = next(item for item in event.allocations if item.shareholder_id == shareholder.id)
                amount = allocation.share_count
                value = allocation.acquisition_value
                event_type = "N"
            else:
                amount = event.share_count
                value = event.consideration
                event_type = "K"
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
            _data(disposal, "AksjerArvMvOmsattType-datadef-17753", "17753", "S")
            _data(disposal, "AksjerArvMvOmsattTidspunkt-datadef-17754", "17754", _dt(event.timestamp))
            _data(disposal, "AksjerArvMvOmsatt-datadef-17755", "17755", event.consideration)
            buyer = next(item for item in case.shareholders if item.id == event.buyer_shareholder_id)
            if buyer.kind == ShareholderKind.NORWEGIAN_PERSON:
                _data(disposal, "AksjonarOvertakendeFodselsnummer-datadef-26532", "26532", buyer.national_id)
            else:
                _data(disposal, "AksjonarOvertakendeOrganisasjonsnummer-datadef-26533", "26533", buyer.org_number)

    return root


def _shareholder_has_acquisition(event: FormationEvent | ShareSaleEvent | DividendEvent, shareholder_id: str) -> bool:
    if isinstance(event, FormationEvent):
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
    if float(value).is_integer():
        return f"{int(value)} kr"
    return f"{value:.2f} kr"


def _dt(value) -> str:
    return value.replace(microsecond=0).isoformat()


def _xml_to_string(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
