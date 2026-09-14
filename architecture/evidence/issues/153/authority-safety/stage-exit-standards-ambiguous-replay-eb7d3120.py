"""No provider/DB calls: two invocations of the exact owned public rehearsal."""
import asyncio,copy,json,sys
from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsAuthorityError,AnnualAccountsRehearsalConfiguration,rehearse_annual_accounts
CONFIG=AnnualAccountsRehearsalConfiguration(approved_test_write='true',authority_environment='test',scope='altinn:instances.read altinn:instances.write',system_user_org='310279617',external_reference='synthetic',contact_email='x@example.invalid',approval_date='2026-06-30',confirming_representative='Synthetic Person')
class IO:
 def __init__(self,failure):self.failure=failure;self.saved=None;self.calls=[];self.failed=False
 def load_case(self):return {'synthetic':True,'environment':'test','company':{'orgNumber':'310279617','incomeYear':2025},'ledgerEntries':[]}
 def load_evidence(self):return copy.deepcopy(self.saved)
 def save_evidence(self,evidence):self.saved=copy.deepcopy(evidence)
 def evidence_filename(self):return 'in-memory-evidence.json'
 def case_filename(self):return 'synthetic.json'
 def revision(self):return 'eb7d312054c32a8e94dd9d0c8bf9f22dcf9a12fa'
 def timestamp(self):return '2026-09-14T12:00:00.000Z'
 def generate(self,*args):return {'mainFormXml':'<main/>','companyAccountsXml':'<accounts/>','feedback':[]}
 def validate_documents(self,*args):pass
 async def connect(self,*args):return self
 async def effect(self,name):
  self.calls.append(name)
  if name==self.failure and not self.failed:
   self.failed=True
   raise AnnualAccountsAuthorityError('Response lost after effect.',code='ANNUAL_ACCOUNTS_NETWORK_ERROR',retryable=True)
 async def create_instance(self,**kw):
  await self.effect('create_instance')
  return {'id':'created-instance','dataIds':{'mainForm':'main','companyAccounts':'accounts'},'processTask':'data'}
 async def upload_main_form(self,**kw):await self.effect('upload_main_form')
 async def upload_company_accounts(self,**kw):await self.effect('upload_company_accounts')
 async def validate_instance(self,**kw):
  self.calls.append('validate_instance');return {'hasErrors':False,'issues':[]}
 async def lock_for_signing(self,**kw):
  await self.effect('lock_for_signing');return {'processTask':'signing'}
 async def get_signing_handoff(self,**kw):
  self.calls.append('get_signing_handoff');return {'signingUrl':'https://synthetic.invalid/signing','signed':False,'submitted':False}
async def main():
 out=[]
 for operation in ('create_instance','lock_for_signing'):
  io=IO(operation)
  try:await rehearse_annual_accounts(CONFIG,io)
  except AnnualAccountsAuthorityError:pass
  first=copy.deepcopy(io.saved);split=len(io.calls)
  result=await rehearse_annual_accounts(CONFIG,io)
  out.append({'lostResponseAfter':operation,'firstStoredStatus':first['status'],'firstStoredInstance':first['instance'],'secondInvocationCalls':io.calls[split:],'totalConsequentialCalls':io.calls.count(operation),'finalStatus':result['status'],'mode':'PURE_LOCAL_FAKES_NO_PROVIDER_OR_DB'})
 print(json.dumps(out,indent=2))
asyncio.run(main())
