"""Additional local-fake durability windows; no provider, filesystem journal or DB."""
import asyncio,json
from test_annual_accounts_rehearsal_recovery import EvidenceIO,CONFIG
from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsAuthorityError,rehearse_annual_accounts,prepare_annual_accounts_for_signing
from test_authority_filing_transports import queue,annual_instance,ORG,XML,ALTINN_TOKEN
from talli_backend.adapters.annual_accounts_authority import AnnualAccountsTransport
import httpx
class FaultIO(EvidenceIO):
 def __init__(self,operation,window):super().__init__(operation,'none');self.window=window
 def save_evidence(self,evidence):
  completed=evidence.get('status')==('instance_created' if self.operation=='create_instance' else 'locked')
  pending=evidence.get('pendingAuthorityOperation',{}).get('operation')==self.operation
  if self.window=='persistent_post_effect_write' and (completed or evidence.get('status')=='reconciliation_required'):
   raise OSError('Persistent unavailable journal after confirmed effect')
  if self.window=='interrupt_success_write' and completed:raise KeyboardInterrupt('Interrupted success checkpoint')
  if self.window=='pending_write_failure' and pending:raise OSError('Unable to persist intent')
  super().save_evidence(evidence)
async def main():
 rows=[]
 for operation in ('create_instance','lock_for_signing'):
  for window in ('persistent_post_effect_write','interrupt_success_write','pending_write_failure'):
   io=FaultIO(operation,window)
   try:await rehearse_annual_accounts(CONFIG,io)
   except BaseException:pass
   effects=io.calls.count(operation)
   if window=='pending_write_failure':assert effects==0
   else:
    assert effects==1 and io.saved['pendingAuthorityOperation']['operation']==operation
    before=list(io.calls)
    try:await rehearse_annual_accounts(CONFIG,io);raise AssertionError('rerun accepted')
    except AnnualAccountsAuthorityError as error:assert error.code=='ANNUAL_ACCOUNTS_RECONCILIATION_REQUIRED'
    assert io.calls==before
   rows.append({'operation':operation,'window':window,'effectCount':effects,'status':'PASS'})
 for body,expected in [('<html>upstream service failure</html>',0),('{"validationIssues":"not-an-array"}',0),('[{"severity":1,"code":"BLOCK"}]',0),('[]',1)]:
  transport,requests,_=queue(annual_instance(),httpx.Response(201),httpx.Response(201),httpx.Response(200,text=body),{'currentTask':{'altinnTaskType':'signing'}},annual_instance('signing'))
  try:result=await prepare_annual_accounts_for_signing(AnnualAccountsTransport(ALTINN_TOKEN,transport=transport),company_org_number=ORG,main_form_xml=XML,company_accounts_xml=XML);code=None
  except AnnualAccountsAuthorityError as error:code=error.code
  locks=sum(req.url.path.endswith('/process/next') for req in requests)
  assert locks==expected and (code is None)==bool(expected)
  rows.append({'validationBody':body,'lockCount':locks,'error':code,'status':'PASS'})
 print(json.dumps(rows,indent=2))
asyncio.run(main())
