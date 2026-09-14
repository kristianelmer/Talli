"""Deterministic RR0002 XML with the released validation order and byte layout."""
from __future__ import annotations

import calendar
import math
import re

from .numbers import SPACE, number, text
from .public import AnnualAccountsDocuments

_ORIDS = (
    ('regnskapsaar', '17102'), ('regnskapsstart', '17103'), ('regnskapsslutt', '17104'), ('valuta', '34984'),
    ('sumDriftskostnad/aarets', '17126'), ('sumFinansinntekter/aarets', '153'), ('sumFinanskostnader/aarets', '17130'),
    ('resultatFoerSkattekostnad/aarets', '167'), ('skattekostnad/aarets', '11835'), ('aarsresultat/aarets', '172'),
    ('investeringAksjerAndeler/aarets', '7100'), ('sumFinansielleAnleggsmidler/aarets', '5267'),
    ('sumBankinnskuddKontanter/aarets', '29042'), ('sumEiendeler/aarets', '219'),
    ('sumInnskuttEgenkapital/aarets', '3730'), ('annenEgenkapital/aarets', '3274'), ('sumEgenkapital/aarets', '250'),
    ('betalbarSkatt/aarets', '2483'), ('sumKortsiktigGjeld/aarets', '85'), ('sumGjeld/aarets', '1119'), ('antallAarsverk', '37467'),
)
_FINANCIAL = (
    ('operatingCosts', 'sumDriftskostnad/aarets'), ('financialIncome', 'sumFinansinntekter/aarets'),
    ('financialCosts', 'sumFinanskostnader/aarets'), ('resultBeforeTax', 'resultatFoerSkattekostnad/aarets'),
    ('taxExpense', 'skattekostnad/aarets'), ('annualResult', 'aarsresultat/aarets'),
    ('investments', 'investeringAksjerAndeler/aarets'), ('financialFixedAssets', 'sumFinansielleAnleggsmidler/aarets'),
    ('bank', 'sumBankinnskuddKontanter/aarets'), ('assets', 'sumEiendeler/aarets'),
    ('contributedEquity', 'sumInnskuttEgenkapital/aarets'), ('retainedEquity', 'annenEgenkapital/aarets'),
    ('equity', 'sumEgenkapital/aarets'), ('taxPayable', 'betalbarSkatt/aarets'),
    ('shortTermDebt', 'sumKortsiktigGjeld/aarets'), ('debt', 'sumGjeld/aarets'), ('annualFullTimeEquivalents', 'antallAarsverk'),
)


def _whole(value, label):
    parsed = number(value)
    if not math.isfinite(parsed) or not parsed.is_integer() or abs(parsed) > 9007199254740991:
        raise ValueError(f'RR0002-felt {label} må oppgis i hele kroner.')
    return parsed


def _text(value, limit, label):
    if not isinstance(value, str) or value != value.strip(SPACE) or not value or len(value.encode('utf-16-le', 'surrogatepass')) // 2 > limit:
        raise ValueError(f'{label} er påkrevd og kan ha maksimalt {limit} tegn.')
    if re.search(r'[\x00-\x1f\x7f]', value):
        raise ValueError(f'{label} inneholder ugyldige kontrolltegn.')
    return value


def _pattern(value, pattern, message):
    if not isinstance(value, str) or value != value.strip(SPACE) or not re.fullmatch(pattern, value):
        raise ValueError(message)
    return value


def _date(value):
    message = 'Fastsettelsesdato må være en gyldig dato i formatet YYYY-MM-DD.'
    match = re.fullmatch(r'([0-9]{4})-([0-9]{2})-([0-9]{2})', value) if isinstance(value, str) else None
    if match:
        year, month, day = map(int, match.groups())
        # Date.UTC maps 0..99 to 1900..1999, so the original equality check fails.
        if year >= 100 and 1 <= month <= 12 and 1 <= day <= calendar.monthrange(year, month)[1]:
            return value
    raise ValueError(message)


def _consistent(v):
    for label, value in v.items():
        if label not in ('resultBeforeTax', 'annualResult', 'retainedEquity') and value < 0:
            raise ValueError(f'RR0002-felt {label} kan ikke være negativt i støttet løype.')
    checks = (
        (v['financialFixedAssets'] == v['investments'], 'Sum finansielle anleggsmidler må samsvare med støttede investeringer.'),
        (v['resultBeforeTax'] == v['financialIncome'] - v['operatingCosts'] - v['financialCosts'], 'Resultat før skattekostnad stemmer ikke med resultatpostene.'),
        (v['annualResult'] == v['resultBeforeTax'] - v['taxExpense'], 'Årsresultat stemmer ikke med resultat før skatt og skattekostnad.'),
        (v['assets'] == v['investments'] + v['bank'], 'Sum eiendeler stemmer ikke med støttede eiendeler.'),
        (v['equity'] == v['contributedEquity'] + v['retainedEquity'], 'Sum egenkapital stemmer ikke med egenkapitalpostene.'),
        (v['debt'] == v['shortTermDebt'] and v['taxPayable'] <= v['shortTermDebt'], 'Sum gjeld stemmer ikke med støttet kortsiktig gjeld.'),
        (v['assets'] == v['equity'] + v['debt'], 'RR0002-balanse: eiendeler er ikke lik egenkapital og gjeld.'),
    )
    for valid, message in checks:
        if not valid:
            raise ValueError(message)


def render(input):
    candidate = input.candidate
    for attribute, key, expected in (
        ('schema_type', 'schemaType', 'aarsregnskap-vanlig-202406'),
        ('main_form_format_id', 'hovedskjemaDataFormatId', '1266'),
        ('main_form_format_version', 'hovedskjemaDataFormatVersion', '51820'),
        ('accounts_format_id', 'selskapsregnskapDataFormatId', '758'),
        ('accounts_format_version', 'selskapsregnskapDataFormatVersion', '51980'),
    ):
        if getattr(candidate, attribute) != expected:
            raise ValueError(f'RR0002 {key} må være {expected}.')
    fields = {}
    for tag, orid in _ORIDS:
        matches = [field for field in candidate.fields if field['tag'] == tag]
        if len(matches) != 1:
            raise ValueError(f'RR0002-felt {tag} må finnes nøyaktig én gang.')
        if matches[0]['orid'] != orid:
            raise ValueError(f'RR0002-felt {tag} må bruke offisiell orid {orid}.')
        fields[tag] = matches[0]['value']
    blocks = sorted((item['code'] for item in candidate.feedback if item['level'] == 'block'), key=lambda value: value.encode('utf-16-be', 'surrogatepass'))
    if blocks:
        raise ValueError(f'Årsregnskap har blokkerende avvik: {", ".join(blocks)}.')
    org = _pattern(input.organization_number, r'[0-9]{9}', 'Organisasjonsnummer må inneholde 9 siffer.')
    name = _text(input.company_name, 175, 'Virksomhetsnavn')
    email = _pattern(input.contact_email, f'[^{SPACE}@]+@[^{SPACE}@]+\\.[^{SPACE}@]+', 'Kontakt-e-post er ugyldig.')
    approval = _date(input.approval_date)
    representative = _text(input.confirming_representative, 70, 'Bekreftende selskapsrepresentant')
    year = _whole(fields['regnskapsaar'], 'regnskapsaar')
    if fields['regnskapsstart'] != f'{text(year)}-01-01' or fields['regnskapsslutt'] != f'{text(year)}-12-31':
        raise ValueError('RR0002-rendereren støtter bare komplett kalenderår.')
    if approval < f'{text(year)}-12-31':
        raise ValueError('Fastsettelsesdato kan ikke være før regnskapsperioden er avsluttet.')
    if fields['valuta'] != 'NOK':
        raise ValueError('RR0002-rendereren støtter bare NOK.')
    values = {label: _whole(fields[tag], tag) for label, tag in _FINANCIAL}
    _consistent(values)
    return AnnualAccountsDocuments(_main_form(org, name, email, approval, representative, year), _company_accounts(values))


def _escape(value):
    return value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;')


def _main_form(org, name, email, approval, representative, year):
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<melding xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns="http://schema.brreg.no/regnsys/aarsregnskap_vanlig" dataFormatId="1266" dataFormatVersion="51820" tjenestehandling="aarsregnskap_vanlig" tjeneste="regnskap">
  <Innsender>
    <enhet>
      <organisasjonsnummer orid="18">{_escape(org)}</organisasjonsnummer>
      <organisasjonsform orid="756">AS</organisasjonsform>
      <navn orid="1">{_escape(name)}</navn>
    </enhet>
    <kontaktperson>
      <e-post orid="19022">{_escape(email)}</e-post>
    </kontaktperson>
    <opplysningerInnsending>
      <noteMaskinellBehandling orid="37499">20</noteMaskinellBehandling>
      <systemNavn orid="39007">Talli</systemNavn>
    </opplysningerInnsending>
  </Innsender>
  <Skjemainnhold>
    <regnskapsperiode>
      <regnskapsaar orid="17102">{text(year)}</regnskapsaar>
      <regnskapsstart orid="17103">{text(year)}-01-01</regnskapsstart>
      <regnskapsslutt orid="17104">{text(year)}-12-31</regnskapsslutt>
    </regnskapsperiode>
    <konsern>
      <morselskap orid="4168">nei</morselskap>
    </konsern>
    <regnskapsprinsipper>
      <smaaForetak orid="8079">ja</smaaForetak>
      <regnskapsreglerSelskap orid="25021">nei</regnskapsreglerSelskap>
    </regnskapsprinsipper>
    <fastsettelse>
      <fastsettelsedato orid="17105">{_escape(approval)}</fastsettelsedato>
      <bekreftendeSelskapsrepresentant orid="19023">{_escape(representative)}</bekreftendeSelskapsrepresentant>
    </fastsettelse>
    <revisjonRegnskapsfoerer>
      <aarsregnskapIkkeRevideres orid="34669">ja</aarsregnskapIkkeRevideres>
      <aarsregnskapUtarbeidetAutorisertRegnskapsfoerer orid="34670">nei</aarsregnskapUtarbeidetAutorisertRegnskapsfoerer>
      <tjenestebistandEksternAutorisertRegnskapsfoerer orid="34671">nei</tjenestebistandEksternAutorisertRegnskapsfoerer>
    </revisjonRegnskapsfoerer>
  </Skjemainnhold>
</melding>
'''


def _company_accounts(values):
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<melding xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns="http://schema.brreg.no/regnsys/aarsregnskap_vanlig/underskjema" dataFormatId="758" dataFormatVersion="51980" versjon="1.1" tjenestehandling="aarsregnskap_vanlig_underskjema" tjeneste="regnskap">
  <Rapport-RR0002U>
    <aarsregnskap>
      <regnskapstype orid="25942">S</regnskapstype>
      <valuta orid="34984">NOK</valuta>
      <valoer orid="28974">H</valoer>
    </aarsregnskap>
  </Rapport-RR0002U>
  <Skjemainnhold-RR0002U>
    <resultatregnskapDriftsresultat>
      <driftsresultat><aarets orid="146">{text(-values["operatingCosts"])}</aarets></driftsresultat>
      <kostnad><sumDriftskostnad><aarets orid="17126">{text(values["operatingCosts"])}</aarets></sumDriftskostnad></kostnad>
    </resultatregnskapDriftsresultat>
    <resultatregnskapFinansinntekt>
      <nettoFinans><aarets orid="158">{text(values["financialIncome"] - values["financialCosts"])}</aarets></nettoFinans>
      <finansinntekt><sumFinansinntekter><aarets orid="153">{text(values["financialIncome"])}</aarets></sumFinansinntekter></finansinntekt>
      <finanskostnad><sumFinanskostnader><aarets orid="17130">{text(values["financialCosts"])}</aarets></sumFinanskostnader></finanskostnad>
    </resultatregnskapFinansinntekt>
    <resultatregnskapResultat>
      <resultat>
        <resultatFoerSkattekostnad><aarets orid="167">{text(values["resultBeforeTax"])}</aarets></resultatFoerSkattekostnad>
        <skattekostnad><aarets orid="11835">{text(values["taxExpense"])}</aarets></skattekostnad>
        <aarsresultat><aarets orid="172">{text(values["annualResult"])}</aarets></aarsresultat>
      </resultat>
    </resultatregnskapResultat>
    <balanseAnleggsmidlerOmloepsmidler>
      <sumEiendeler><aarets orid="219">{text(values["assets"])}</aarets></sumEiendeler>
      <balanseAnleggsmidler>
        <sumAnleggsmidler><aarets orid="217">{text(values["investments"])}</aarets></sumAnleggsmidler>
        <balanseFinansielleAnleggsmidler>
          <investeringAksjerAndeler><aarets orid="7100">{text(values["investments"])}</aarets></investeringAksjerAndeler>
          <sumFinansielleAnleggsmidler><aarets orid="5267">{text(values["financialFixedAssets"])}</aarets></sumFinansielleAnleggsmidler>
        </balanseFinansielleAnleggsmidler>
      </balanseAnleggsmidler>
      <balanseOmloepsmidler>
        <sumOmloepsmidler><aarets orid="194">{text(values["bank"])}</aarets></sumOmloepsmidler>
        <balanseOmloepsmidlerInvesteringerBankinnskuddKontanter>
          <bankinnskuddKontanter>
            <sumBankinnskuddKontanter><aarets orid="29042">{text(values["bank"])}</aarets></sumBankinnskuddKontanter>
          </bankinnskuddKontanter>
        </balanseOmloepsmidlerInvesteringerBankinnskuddKontanter>
      </balanseOmloepsmidler>
    </balanseAnleggsmidlerOmloepsmidler>
    <balanseEgenkapitalGjeld>
      <sumEgenkapitalGjeld><aarets orid="251">{text(values["assets"])}</aarets></sumEgenkapitalGjeld>
      <balanseEgenkapitalInnskuttOpptjentEgenkapital>
        <innskuttEgenkapital>
          <sumInnskuttEgenkapital><aarets orid="3730">{text(values["contributedEquity"])}</aarets></sumInnskuttEgenkapital>
        </innskuttEgenkapital>
        <opptjentEgenkaiptal>
          <annenEgenkapital><aarets orid="3274">{text(values["retainedEquity"])}</aarets></annenEgenkapital>
          <sumOpptjentEgenkapital><aarets orid="9702">{text(values["retainedEquity"])}</aarets></sumOpptjentEgenkapital>
          <sumEgenkapital><aarets orid="250">{text(values["equity"])}</aarets></sumEgenkapital>
        </opptjentEgenkaiptal>
      </balanseEgenkapitalInnskuttOpptjentEgenkapital>
      <balanseGjeldOversikt>
        <sumGjeld><aarets orid="1119">{text(values["debt"])}</aarets></sumGjeld>
        <balanseKortsiktigGjeld>
          <betalbarSkatt><aarets orid="2483">{text(values["taxPayable"])}</aarets></betalbarSkatt>
          <sumKortsiktigGjeld><aarets orid="85">{text(values["shortTermDebt"])}</aarets></sumKortsiktigGjeld>
        </balanseKortsiktigGjeld>
      </balanseGjeldOversikt>
    </balanseEgenkapitalGjeld>
    <noter>
      <noteAarsverkTjenestePensjon>
        <antallAarsverk orid="37467">{text(values["annualFullTimeEquivalents"])}</antallAarsverk>
      </noteAarsverkTjenestePensjon>
    </noter>
  </Skjemainnhold-RR0002U>
</melding>
'''
