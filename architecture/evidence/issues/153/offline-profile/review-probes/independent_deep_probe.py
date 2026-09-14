import json
from pathlib import Path
from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsSource,build_annual_accounts
c=json.loads(Path('architecture/evidence/issues/153/characterization/legacy-pure-characterization.json').read_text())
results=[]
for depth in (100,600,1200):
 value=json.loads(json.dumps(c['payloadCases'][0]['input'])); extra='ignored'
 for _ in range(depth):extra=[extra]
 value['annualData']['ignored']=extra
 try:
  result=build_annual_accounts(AnnualAccountsSource(value['incomeYear'],value['annualData'],tuple(value['ledgerEntries'])))
  results.append(dict(depth=depth,status='ok',fieldCount=len(result.fields)))
 except Exception as error:results.append(dict(depth=depth,status=type(error).__name__,message=str(error)))
print(json.dumps(results,indent=2))
