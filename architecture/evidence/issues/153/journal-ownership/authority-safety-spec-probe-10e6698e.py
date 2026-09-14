"""Pinned public/adapter probes; private file IO only, no provider or database."""
import asyncio,ast,copy,json,tempfile
from pathlib import Path
from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsAuthorityError,rehearse_annual_accounts,prepare_annual_accounts_for_signing
from talli_backend.authority_tools._filing import read_evidence,write_evidence
from test_annual_accounts_rehearsal_recovery import EvidenceIO,CONFIG
from test_authority_filing_transports import queue,annual_instance,ORG,XML,ALTINN_TOKEN
from talli_backend.adapters.annual_accounts_authority import AnnualAccountsTransport
import httpx
PRIVATE=Path(__file__).parent
original=PRIVATE/'stage-exit-standards-ambiguous-replay-eb7d3120.py'
tree=ast.parse(original.read_text());tree.body.pop();namespace={};exec(compile(tree,str(original),'exec'),namespace)
async def main():
 results=[]
 for op in ('create_instance','lock_for_signing'):
  io=namespace['IO'](op)
  try:await rehearse_annual_accounts(namespace['CONFIG'],io)
  except AnnualAccountsAuthorityError as first:assert first.code=='ANNUAL_ACCOUNTS_RECONCILIATION_REQUIRED'
  before=list(io.calls)
  try:await rehearse_annual_accounts(namespace['CONFIG'],io)
  except AnnualAccountsAuthorityError as second:assert second.code=='ANNUAL_ACCOUNTS_RECONCILIATION_REQUIRED'
  else:raise AssertionError('retry admitted')
  assert io.calls==before and io.calls.count(op)==1
  results.append({'case':'original_lost_response_'+op,'effectCount':1,'rerunCalls':[]})
 for body in ('<html>upstream service failure</html>','{"validationIssues":"not-an-array"}','[]'):
  transport,requests,_=queue(annual_instance(),httpx.Response(201),httpx.Response(201),httpx.Response(200,text=body),{'currentTask':{'altinnTaskType':'signing'}},annual_instance('signing'))
  error=None
  try:await prepare_annual_accounts_for_signing(AnnualAccountsTransport(ALTINN_TOKEN,transport=transport),company_org_number=ORG,main_form_xml=XML,company_accounts_xml=XML)
  except AnnualAccountsAuthorityError as e:error=e.code
  locks=sum(r.method=='PUT' and r.url.path.endswith('/process/next') for r in requests)
  assert (error,locks)==((None,1) if body=='[]' else ('ANNUAL_ACCOUNTS_VALIDATION_RESPONSE_INVALID',0))
  results.append({'case':'original_validation','body':body,'error':error,'lockCount':locks})
 for op in ('create_instance','lock_for_signing'):
  for when in ('before_pending','after_pending','before_success','after_success'):
   with tempfile.TemporaryDirectory(prefix='accounts-spec-journal-',dir=PRIVATE) as temp:
    class FileIO(EvidenceIO):
     def __init__(self):super().__init__(op,'none');self.path=Path(temp)/'evidence.json';self.failure_raised=False
     def load_evidence(self):return read_evidence(self.path)
     def save_evidence(self,value):
      pending=value.get('pendingAuthorityOperation',{}).get('operation')==op
      completed=value.get('status')==('instance_created' if op=='create_instance' else 'locked') and not pending
      target=(pending if 'pending' in when else completed) and not self.failure_raised
      if target and when.startswith('before'):
       self.failure_raised=True;raise OSError('private before-atomic-replace failure')
      write_evidence(self.path,value);self.saved=read_evidence(self.path)
      if target:
       self.failure_raised=True;raise OSError('private after-atomic-replace failure')
    io=FileIO()
    try:await rehearse_annual_accounts(CONFIG,io)
    except AnnualAccountsAuthorityError as e:assert e.code=='ANNUAL_ACCOUNTS_RECONCILIATION_REQUIRED'
    assert read_evidence(io.path)['pendingAuthorityOperation']['operation']==op
    before=list(io.calls)
    try:await rehearse_annual_accounts(CONFIG,io)
    except AnnualAccountsAuthorityError as e:assert e.code=='ANNUAL_ACCOUNTS_RECONCILIATION_REQUIRED'
    else:raise AssertionError('file journal admitted retry')
    assert before==io.calls
    expected=0 if 'pending' in when else 1;assert io.calls.count(op)==expected
    assert io.path.stat().st_mode&0o777==0o600
    results.append({'case':'actual_atomic_file_'+op+'_'+when,'effectCount':expected,'rerunCalls':[],'fileMode':'0600'})
 print(json.dumps({'status':'PASS','count':len(results),'cases':results,'limits':'Local fake ports and private temporary files only; no provider/DB/process-crash/power-loss claim.'},indent=2))
asyncio.run(main())
