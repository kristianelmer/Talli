"""Freeze the existing offline contract separately from the web RR0002 profile."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

assert sys.version_info[:3] == (3, 12, 12), sys.version
ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from holding_core.annual import AnnualData, build_annual_accounts_payload, assess_annual_accounts_readiness, simulate_annual_accounts
from holding_core.validation import run_annual_compliance_validation

BASELINE = '5b74340ca75f215b43d754c6bf0fc49ef5974b0b'
paths = ['holding_core/annual.py', 'holding_core/validation.py', 'holding_core/workspace.py', 'holding_cli/main.py']
fixtures = sorted(ROOT.glob('tests/fixtures/annual_validation/*.json'))
paths += [str(p.relative_to(ROOT)) for p in fixtures]
sources = {}
for path in paths:
    raw = Path(path).read_bytes()
    assert raw == subprocess.check_output(['git', 'show', f'{BASELINE}:{path}'])
    sources[path] = hashlib.sha256(raw).hexdigest()
base = json.loads((ROOT / 'tests/fixtures/annual_validation/simple_holding_pass.json').read_text())['annual_data']
cases = []

def add(name, mutate=None):
    raw = copy.deepcopy(base)
    if mutate:
        mutate(raw)
    try:
        data = AnnualData.model_validate(raw)
        output = {
            'payload': build_annual_accounts_payload(data).model_dump(mode='json'),
            'readiness': assess_annual_accounts_readiness(data).model_dump(mode='json'),
            'simulation': simulate_annual_accounts(data).model_dump(mode='json'),
        }
    except Exception as error:
        output = {'error': {'name': type(error).__name__, 'message': str(error)}}
    cases.append({'id': name, 'input': raw, 'output': output})

add('supported-offline')
for key, value in [('annual_full_time_equivalents', None), ('annual_full_time_equivalents', -1), ('annual_full_time_equivalents', 0.5), ('audit_required', True), ('small_enterprise', False), ('annual_report_required', True), ('cash_flow_statement_required', True), ('sustainability_reporting_required', True), ('fiscal_year_is_calendar_year', False), ('prior_year_figures_confirmed', False)]:
    add(f'{key}-{value}', lambda raw, key=key, value=value: raw.update({key: value}))
for key, value in [('general_meeting_approved', False), ('bank_balance_confirmed', False), ('has_unpaid_items', True), ('authority_to_submit_confirmed', False)]:
    add(f'interview-{key}', lambda raw, key=key, value=value: raw['interview'].update({key: value}))
add('missing-document', lambda raw: raw.update(documents=[{'id': 'synthetic-doc', 'document_type': 'receipt', 'name': 'Synthetic missing receipt', 'status': 'missing_accepted_warning'}]))
for account in ['1300', '1310', '1350', '1800', '1810', '1815', '1920', '7770', '6700', '6705', '6420', '7790', '6720', '7795', '8070', '8071', '8074', '8050', '8090', '8171', '8174', '8300', '2500', '2000', '2050', '2255']:
    def mutate(raw, account=account):
        entry = copy.deepcopy(raw['posted_entries'][0])
        entry['lines'] = [{'account': account, 'description': 'Synthetic profile probe', 'debit': 13.755, 'credit': 0}]
        raw['posted_entries'] = [entry]
    add(f'account-{account}', mutate)
for amount in [0.005, 0.015, 1.005, 2.675]:
    def mutate(raw, amount=amount):
        entry = copy.deepcopy(raw['posted_entries'][0])
        entry['lines'] = [{'account': '1920', 'description': 'Synthetic rounding probe', 'debit': amount, 'credit': 0}]
        raw['posted_entries'] = [entry]
    add(f'python-round-{amount}', mutate)
validation = run_annual_compliance_validation(fixtures).model_dump(mode='json')
# The validation report has a wall clock timestamp; record it without claiming deterministic time.
result = {'schemaVersion': '1.0', 'sourceRevision': BASELINE, 'runtime': sys.version, 'sources': sources, 'profile': 'Existing offline public-data simulation; not live RR0002 filing', 'cases': cases, 'validation': validation}
data = (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode()
with Path(sys.argv[1]).open('xb') as output:
    output.write(data)
print(json.dumps({'caseCount': len(cases), 'sha256': hashlib.sha256(data).hexdigest()}))
