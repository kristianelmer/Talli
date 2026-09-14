"""Company Tax's characterized 2025 calculation and ordered authority fields.

Annual estimates intentionally retain their distinct entry-based aggregation.
This module neither decides filing permission nor reads other capabilities.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from .numbers import money, nonnegative, number, rounded, total, truthy, text as js_string

TAX = 'skattemeldingUpersonlig'
BUSINESS = 'naeringsspesifikasjon'
TAX_XSD = 'skattemeldingUpersonlig_v5_ekstern.xsd'
BUSINESS_XSD = 'naeringsspesifikasjon_v6_ekstern.xsd'


def _amount(action, key):
    value = number(action['payload'].get(key))
    return value if math.isfinite(value) else 0.0


def _sale_result(action):
    return _amount(action, 'book_gain_or_loss' if 'book_gain_or_loss' in action['payload'] else 'gain_or_loss')


def _sale_component(action, key, fallback):
    return _amount(action, key) if key in action['payload'] else fallback


def _ledger_totals(entries):
    lines = [line for entry in entries for line in entry['lines']]

    def balance(account):
        matching = [line for line in lines if line.get('account') == account]
        return money(total(number(line.get('debit')) for line in matching) - total(number(line.get('credit')) for line in matching))

    def debit(account):
        return money(total(number(line.get('debit')) for line in lines if line.get('account') == account))

    def credit(account):
        return money(-balance(account))

    investments = [{'account': account, 'amount': balance(account)} for account in ('1300', '1310', '1350', '1800', '1810', '1815') if balance(account) != 0]
    groups = {}
    for account in ('6700', '6705', '6420', '6720', '7770', '7790', '7795'):
        value = debit(account)
        if value == 0:
            continue
        target = {'6705': '6700', '7795': '7790'}.get(account, account)
        groups[target] = money(groups[target] + value) if target in groups else value
    costs = [{'account': account, 'amount': groups[account]} for account in sorted(groups)]
    return {
        'bankBalance': balance('1920'), 'investmentBalances': investments,
        'adminCostsByAccount': costs, 'adminCosts': money(total(item['amount'] for item in costs)),
        'dividendAndGainIncome': money(credit('8070') + credit('8071') + credit('8074')),
        'interestIncome': credit('8050'), 'shareSaleLoss': money(debit('8090') + debit('8171') + debit('8174')),
        'shareCapital': credit('2000'), 'retainedEarnings': credit('2050'),
        'shortTermDebt': credit('2255') + credit('2990'),
    }


def feedback(input):
    result = []

    def add(level, code, message):
        if all(item['code'] != code for item in result):
            result.append({'level': level, 'code': code, 'message': message, 'source': 'company_tax_return_payload'})

    annual, entries, actions = input['annualData'], input['ledgerEntries'], input['holdingActions']
    if annual is None:
        add('block', 'tax_return_annual_data_missing', 'Year-end interview må være fullført før skattemelding-payload.')
        return result
    answers = annual['answers']
    if truthy(answers.get('shareholder_loans')):
        add('block', 'tax_return_shareholder_loan_review_required', 'Aksjonær-/konsernlån krever gjennomgang før skattemelding.')
    if truthy(answers.get('declared_owner_dividends')):
        add('block', 'tax_return_owner_dividend_review_required', 'Utbytte til eier krever egenkapitalavstemming før automatisk skattemelding.')
    if any(entry['entry_type'] == 'shareholder_loan' for entry in entries):
        add('block', 'tax_return_shareholder_loan_review_required', 'Aksjonærlån er utenfor automatisk skattemelding-løype.')
    if truthy(answers.get('bought_or_sold_shares')) or any(action['action_type'] in ('share_purchase', 'share_sale') and not isinstance(action['payload'].get('calculation_id'), str) for action in actions):
        add('warning', 'tax_return_share_sale_or_purchase_review', 'Kjøp/salg av aksjer må ha fritaksmetodeklassifisering og dokumentasjon.')
    for action in actions:
        if action['risk_level'] == 'block':
            add('block', 'tax_return_blocking_holding_action', 'Blokkerende holdinghandling må løses før skattemelding.')
        if action['action_type'] in ('dividend_received', 'fund_distribution_received', 'share_purchase', 'share_sale') and action['payload'].get('tax_treatment') != 'fritaksmetoden':
            add('block', 'tax_return_unclear_fritaksmetoden', 'Kun sikker fritaksmetodebehandling støttes i første skattemelding-løype.')
    if any(entry['risk_flags'] and not truthy(entry.get('warning_accepted_at')) for entry in entries):
        add('warning', 'tax_return_manual_journal_warning_unaccepted', 'Manuelle posteringer må aksepteres før skattemelding.')
    if truthy(annual.get('no_activity_confirmed')) and (any(e['entry_type'] != 'opening_balance' for e in entries) or any(a['action_type'] != 'tax_settlement' for a in actions)):
        add('warning', 'tax_return_no_activity_with_activity_data', 'No-activity er bekreftet, men året har posteringer eller holdinghandlinger.')
    totals = _ledger_totals(entries)
    classified = money(total(_amount(a, 'gross_amount') if a['action_type'] == 'dividend_received' else _amount(a, 'dividend_portion') if a['action_type'] == 'fund_distribution_received' else nonnegative(_sale_result(a)) if a['action_type'] == 'share_sale' else 0 for a in actions))
    losses = money(total(nonnegative(-_sale_result(a)) for a in actions if a['action_type'] == 'share_sale'))
    if classified > 0 and classified != totals['dividendAndGainIncome']:
        add('block', 'tax_return_financial_income_classification_mismatch', 'Finansinntekt i hovedbok stemmer ikke med klassifiserte utbytter og aksjegevinster.')
    if losses > 0 and losses != totals['shareSaleLoss']:
        add('block', 'tax_return_share_loss_classification_mismatch', 'Aksjetap i hovedbok stemmer ikke med klassifiserte aksjesalg.')
    if not result:
        add('info', 'tax_return_payload_candidate_ready', 'Skattemelding-kandidat kan bygges for lokal validering.')
    return result


def _field(document, path, value, source, evidence):
    return {'authorityDocument': document, 'path': path, 'value': value, 'source': source, 'evidence': evidence}


def _occurrence(base, index, code, value, source, *, balance=False):
    if value == 0:
        return []
    prefix, evidence = f'{base}[{index}]', f'2025_resultatregnskapOgBalanse.xml:{code}'
    amount = _field(BUSINESS, prefix + '.beloep.beloep.beloep', value, source, evidence)
    identity = _field(BUSINESS, prefix + '.id', f'{code}-{index}', source, evidence)
    return ([identity, amount] if balance else [amount, identity]) + [_field(BUSINESS, prefix + '.type.resultatOgBalanseregnskapstype', code, source, evidence)]


def _difference(index, kind, value, source):
    if value == 0:
        return []
    prefix = f'forskjellMellomRegnskapsmessigOgSkattemessigVerdi.permanentForskjell[{index}]'
    evidence = '2025_permanentForskjellstype.xml'
    return [_field(BUSINESS, prefix + suffix, v, source, evidence) for suffix, v in (
        ('.id', f'permanent-{index}'), ('.permanentForskjellstype.permanentForskjellstype', kind), ('.beloep.beloep.beloep', value))]


def build(input):
    party = input.get('companyPartyNumber')
    if party is None:
        party = input['companyOrgNumber']
    year = input['incomeYear']
    totals = _ledger_totals(input['ledgerEntries'])
    actions = input['holdingActions']
    dividends = [a for a in actions if a['action_type'] == 'dividend_received']
    distributions = [a for a in actions if a['action_type'] == 'fund_distribution_received']
    sales = [a for a in actions if a['action_type'] == 'share_sale']
    classified = total(_amount(a, 'gross_amount') for a in dividends) + total(_amount(a, 'dividend_portion') for a in distributions)
    dividend = money(classified if truthy(classified) else (totals['dividendAndGainIncome'] if not dividends and not distributions and not sales else 0))
    gain = money(total(nonnegative(_sale_result(a)) for a in sales))
    loss = money(total(nonnegative(-_sale_result(a)) for a in sales))
    exempt_gain = money(total(_sale_component(a, 'exempt_gain', nonnegative(_sale_result(a))) for a in sales))
    taxable_gain = money(total(_sale_component(a, 'taxable_gain', 0) for a in sales))
    nondeductible_loss = money(total(_sale_component(a, 'non_deductible_loss', nonnegative(-_sale_result(a))) for a in sales))
    deductible_loss = money(total(_sale_component(a, 'deductible_loss', 0) for a in sales))
    add_back = money(total(_amount(a, 'taxable_add_back') for a in dividends + distributions))
    accounting = money(totals['dividendAndGainIncome'] + totals['interestIncome'] - totals['adminCosts'] - totals['shareSaleLoss'])
    basis = money(accounting - dividend - gain + loss + add_back + taxable_gain - deductible_loss)
    fields = [
        _field(TAX, 'skattemelding.partsnummer', party, 'current.skattemelding.partsnummer', TAX_XSD),
        _field(TAX, 'skattemelding.inntektsaar', year, 'company.income_year', TAX_XSD),
        _field(TAX, 'skattemelding.inntektOgUnderskudd.' + ('inntekt.naeringsinntekt' if basis >= 0 else 'inntektsfradrag.underskudd') + '.beloepSomHeltall', rounded(abs(basis)), 'reconciliation.taxable_basis', TAX_XSD),
    ]
    for index, action in enumerate(dividends):
        prefix = f'skattemelding.spesifikasjonAvForholdRelevanteForBeskatning.aksjeIAksjonaerregisteret[{index}]'
        fields.extend([
            _field(TAX, prefix + '.id', action['id'], 'holding_actions.dividend_received.id', TAX_XSD),
            _field(TAX, prefix + '.erOmfattetAvFritaksmetoden.boolsk', True, 'holding_actions.dividend_received.tax_treatment', 'tekster_upersonlig.json'),
            _field(TAX, prefix + '.utbytte.beloepSomHeltall', number(action['payload'].get('gross_amount')), 'holding_actions.dividend_received.gross_amount', TAX_XSD),
        ])
    fields.extend([
        _field(BUSINESS, 'naeringsspesifikasjon.partsreferanse', party, 'current.skattemelding.partsnummer', BUSINESS_XSD),
        _field(BUSINESS, 'naeringsspesifikasjon.inntektsaar', year, 'company.income_year', BUSINESS_XSD),
    ])
    for index, cost in enumerate(totals['adminCostsByAccount']):
        fields.extend(_occurrence('resultatregnskap.driftskostnad.annenDriftskostnad.kostnad', index, cost['account'], cost['amount'], f"ledger.{cost['account']}"))
    for base, index, code, value, source in (
        ('resultatregnskap.finansinntekt.inntekt', 0, '8090', dividend, 'holding_actions.dividend_received'),
        ('resultatregnskap.finansinntekt.inntekt', 1, '8050', totals['interestIncome'], 'ledger.8050'),
        ('resultatregnskap.finansinntekt.inntekt', 2, '8074', gain, 'holding_actions.share_sale.book_gain_or_loss'),
        ('resultatregnskap.finanskostnad.kostnad', 0, '8174', loss, 'holding_actions.share_sale.book_gain_or_loss'),
    ):
        fields.extend(_occurrence(base, index, code, value, source))
    for index, investment in enumerate(totals['investmentBalances']):
        account = investment['account']
        base = 'balanseregnskap.omloepsmiddel.balanseverdiForOmloepsmiddel.balanseverdi' if account in ('1810', '1815') else 'balanseregnskap.anleggsmiddel.balanseverdiForAnleggsmiddel.balanseverdi'
        fields.extend(_occurrence(base, index, account, investment['amount'], f'ledger.{account}', balance=True))
    for base, index, code, value, source in (
        ('balanseregnskap.omloepsmiddel.balanseverdiForOmloepsmiddel.balanseverdi', 0, '1920', totals['bankBalance'], 'ledger.1920'),
        ('balanseregnskap.gjeldOgEgenkapital.kortsiktigGjeld.gjeld', 0, '2990', totals['shortTermDebt'], 'ledger.2255_or_2990'),
        ('balanseregnskap.gjeldOgEgenkapital.egenkapital.kapital', 0, '2000', totals['shareCapital'], 'ledger.2000'),
        ('balanseregnskap.gjeldOgEgenkapital.egenkapital.kapital', 1, '2050', totals['retainedEarnings'], 'ledger.2050'),
    ):
        fields.extend(_occurrence(base, index, code, value, source, balance=True))
    for index, kind, value, source in (
        (0, 'tilbakefoeringAvInntektsfoertUtbytte', dividend, 'holding_actions.dividend_received.gross_amount'),
        (1, 'skattepliktigDelAvUtbytterOgUtdelinger', add_back, 'holding_actions.dividend_received.taxable_add_back'),
        (2, 'regnskapsmessigGevinstVedRealisasjonAvFinansielleInstrumenter', exempt_gain, 'holding_actions.share_sale.gain_or_loss'),
        (3, 'regnskapsmessigTapVedRealisasjonAvFinansielleInstrumenter', nondeductible_loss, 'holding_actions.share_sale.gain_or_loss'),
    ):
        fields.extend(_difference(index, kind, value, source))
    for path, value, source, evidence in (
        ('virksomhet.regnskapspliktstype.regnskapspliktstype', 'fullRegnskapsplikt', 'launch_scope', '2025_regnskapsplikttype.xml'),
        ('virksomhet.regnskapsperiode.start.dato', f'{js_string(year)}-01-01', 'calendar_year', BUSINESS_XSD),
        ('virksomhet.regnskapsperiode.slutt.dato', f'{js_string(year)}-12-31', 'calendar_year', BUSINESS_XSD),
        ('virksomhet.virksomhetstype.virksomhetstype', 'oevrigSelskap', 'launch_scope', '2025_virksomhetstype.xml'),
        ('virksomhet.regeltypeForAarsregnskap.regeltypeForAarsregnskap', 'regnskapslovensAlminneligeRegler', 'launch_scope', '2025_regeltypeForAarsregnskap.xml'),
        ('skalBekreftesAvRevisor', False, 'launch_scope', BUSINESS_XSD),
    ):
        fields.append(_field(BUSINESS, 'naeringsspesifikasjon.' + path, value, source, evidence))
    return {
        'schema': {'incomeYear': year,
            TAX: {'type': TAX, 'xsd': TAX_XSD, 'namespace': 'urn:no:skatteetaten:fastsetting:formueinntekt:skattemelding:upersonlig:ekstern:v5'},
            BUSINESS: {'type': BUSINESS, 'xsd': BUSINESS_XSD, 'namespace': 'urn:no:skatteetaten:fastsetting:formueinntekt:naeringsspesifikasjon:ekstern:v6'},
            'codeListYear': 2025, 'evidenceRegister': 'docs/filing/company-tax-return-schema-evidence-register.md'},
        'derived': {'noActivity': bool((input['annualData'] or {}).get('no_activity_confirmed')),
            'adminCosts': totals['adminCosts'], 'interestIncome': totals['interestIncome'], 'dividendIncome': dividend,
            'bookShareSaleGain': gain, 'bookShareSaleLoss': loss, 'exemptShareSaleGain': exempt_gain,
            'taxableShareSaleGain': taxable_gain, 'nonDeductibleShareSaleLoss': nondeductible_loss,
            'deductibleShareSaleLoss': deductible_loss, 'accountingResultBeforeTax': accounting,
            'fritaksmetodenAddBack': add_back, 'taxableBasis': basis, 'estimatedTax': money(nonnegative(basis) * .22)},
        'fields': fields, 'feedback': feedback(input),
    }


def estimate(input):
    entries, actions = input['ledgerEntries'], input['holdingActions']
    costs = []
    for entry in entries:
        if entry['entry_type'] != 'admin_cost':
            continue
        cost = 0.0
        for line in entry['lines']:
            if isinstance(line, Mapping) and 'account' in line and line['account'] != '1920':
                cost = cost + number(line.get('debit')) - number(line.get('credit'))
        costs.append(cost)
    admin = total(costs)
    interest = 0.0
    for entry in entries:
        for line in entry['lines']:
            if isinstance(line, Mapping) and line.get('account') == '8050':
                interest = interest + number(line.get('credit')) - number(line.get('debit'))
    interest = money(interest)
    add_back = total(number(a['payload'].get('taxable_add_back')) for a in actions if a['action_type'] in ('dividend_received', 'fund_distribution_received'))
    gain = total(number(a['payload'].get('taxable_gain')) for a in actions if a['action_type'] == 'share_sale')
    loss = total(number(a['payload'].get('deductible_loss')) for a in actions if a['action_type'] == 'share_sale')
    basis = money(interest + add_back + gain - loss - admin)
    tax = money(nonnegative(basis) * .22)
    return {'adminCosts': money(admin), 'interestIncome': money(interest), 'fritaksmetodenAddBack': money(add_back),
            'taxableShareSaleGain': money(gain), 'deductibleShareSaleLoss': money(loss), 'taxBasis': basis,
            'estimatedTax': tax, 'status': 'payable' if tax > 0 else 'zero'}
