"""Released RR0002 field ordering and Accounts ledger aggregation."""
from __future__ import annotations

from .numbers import money, number, total, text
from .public import AnnualAccountsCandidate


def full_time_equivalents(annual):
    return 0 if annual is None else annual.get('annual_full_time_equivalents', 0)


def feedback(annual):
    if annual is None:
        return []
    result = []

    def block(code, message):
        result.append({'level': 'block', 'code': code, 'message': message, 'source': 'annual_accounts_payload'})

    equivalents = full_time_equivalents(annual)
    if equivalents is None:
        block('annual_accounts_aarsverk_missing', 'Årsverk må oppgis i årsregnskapsnoten.')
    if equivalents is not None and number(equivalents) < 0:
        block('annual_accounts_aarsverk_negative', 'Årsverk kan ikke være negativt.')
    for code, message in (
        ('annual_accounts_audit_required', 'Revisjonsplikt er utenfor enkel holding-AS-løype.'),
        ('annual_accounts_not_small_enterprise', 'Ikke-små foretak krever utvidet årsregnskapsmodell.'),
        ('annual_accounts_annual_report_required', 'Årsberetning er ikke støttet i første årsregnskapsløype.'),
    ):
        if code in annual['confirmations']:
            block(code, message)
    return result


def build(source):
    lines = [line for entry in source.ledger_entries for line in entry['lines']]

    def balance(account):
        matching = [line for line in lines if line.get('account') == account]
        return money(total(number(line.get('debit')) for line in matching) - total(number(line.get('credit')) for line in matching))

    def credit(account):
        return money(-balance(account))

    def debits(accounts):
        return money(total(number(line.get('debit')) for line in lines if line.get('account') in accounts))

    tax_payable = credit('2500')
    investments = money(total(balance(account) for account in ('1300', '1310', '1350', '1800', '1810', '1815')))
    bank = balance('1920')
    costs = debits(('7770', '6700', '6705', '6420', '7790', '6720', '7795'))
    income = money(credit('8070') + credit('8071') + credit('8074') + credit('8050'))
    finance_costs = debits(('8090', '8171', '8174'))
    tax_expense = balance('8300')
    capital = credit('2000')
    debt = money(credit('2255') + tax_payable)
    before_tax = money(income - costs - finance_costs)
    annual_result = money(before_tax - tax_expense)
    retained = money(credit('2050') + annual_result)
    equity = money(capital + retained)
    assets = money(investments + bank)
    equivalents = full_time_equivalents(source.annual_data)
    equivalents = 0 if equivalents is None else equivalents
    fields = (
        ('regnskapsaar', '17102', source.income_year, 'company.income_year'),
        ('regnskapsstart', '17103', f'{text(source.income_year)}-01-01', 'calendar_year'),
        ('regnskapsslutt', '17104', f'{text(source.income_year)}-12-31', 'calendar_year'),
        ('valuta', '34984', 'NOK', 'launch_currency'),
        ('sumDriftskostnad/aarets', '17126', costs, 'ledger.expense_accounts'),
        ('sumFinansinntekter/aarets', '153', income, 'ledger.8070_8050'),
        ('sumFinanskostnader/aarets', '17130', finance_costs, 'ledger.8090'),
        ('resultatFoerSkattekostnad/aarets', '167', before_tax, 'derived'),
        ('skattekostnad/aarets', '11835', tax_expense, 'ledger.8300'),
        ('aarsresultat/aarets', '172', annual_result, 'derived'),
        ('investeringAksjerAndeler/aarets', '7100', investments, 'ledger.1300_1310_1350_1800_1810_1815'),
        ('sumFinansielleAnleggsmidler/aarets', '5267', investments, 'derived'),
        ('sumBankinnskuddKontanter/aarets', '29042', bank, 'ledger.1920'),
        ('sumEiendeler/aarets', '219', assets, 'derived'),
        ('sumInnskuttEgenkapital/aarets', '3730', capital, 'ledger.2000'),
        ('annenEgenkapital/aarets', '3274', retained, 'ledger.2050_and_result'),
        ('sumEgenkapital/aarets', '250', equity, 'derived'),
        ('betalbarSkatt/aarets', '2483', tax_payable, 'ledger.2500'),
        ('sumKortsiktigGjeld/aarets', '85', debt, 'ledger.2255_2500'),
        ('sumGjeld/aarets', '1119', debt, 'derived'),
        ('antallAarsverk', '37467', equivalents, 'annual_accounts.notes'),
    )
    return AnnualAccountsCandidate('aarsregnskap-vanlig-202406', '1266', '51820', '758', '51980',
        {'annualFullTimeEquivalents': equivalents},
        tuple(dict(zip(('tag', 'orid', 'value', 'source'), field)) for field in fields),
        tuple(feedback(source.annual_data)))
