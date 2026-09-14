import json
from pathlib import Path
from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsSource,build_annual_accounts
fixture=json.loads(Path('architecture/evidence/issues/153/characterization/legacy-pure-characterization.json').read_text())
value=fixture['payloadCases'][0]['input']
metadata='ignored'
for _ in range(600):metadata=[metadata]
value['ledgerEntries'][0]['metadata']=metadata
try:
 source=AnnualAccountsSource(value['incomeYear'],value['annualData'],tuple(value['ledgerEntries']))
 print('canonical',len(build_annual_accounts(source).fields))
except Exception as e:print(type(e).__name__,str(e))
