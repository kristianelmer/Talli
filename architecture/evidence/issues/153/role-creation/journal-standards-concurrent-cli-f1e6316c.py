"""Actual CLI run + actual local JSON journal; only provider/clock/XML are fake."""
import asyncio,json,tempfile
from pathlib import Path
from unittest.mock import patch
from talli_backend.authority_tools.annual_accounts_test import run
from talli_backend.adapters import local_annual_accounts_rehearsal as local
async def main():
 ready=asyncio.Event();release=asyncio.Event();state={'arrived':0,'creates':0,'locks':0}
 class Client:
  async def create_instance(self,**_):
   state['creates']+=1
   return {'id':f'instance-{state["creates"]}','dataIds':{'mainForm':'main','companyAccounts':'accounts'},'processTask':'data'}
  async def upload_main_form(self,**_):pass
  async def upload_company_accounts(self,**_):pass
  async def validate_instance(self,**_):return {'hasErrors':False,'issues':[]}
  async def lock_for_signing(self,**_):state['locks']+=1;return {'processTask':'signing'}
  async def get_signing_handoff(self,**kw):return {'signingUrl':'https://synthetic.invalid/'+kw['instance_id']}
 async def connect(*_):
  state['arrived']+=1
  ready.set()
  await release.wait()
  return Client()
 with tempfile.TemporaryDirectory(prefix='accounts153-concurrent-cli-') as directory:
  case=Path(directory)/'case.json';journal=Path(directory)/'evidence.json'
  case.write_text(json.dumps({'synthetic':True,'environment':'test','company':{'orgNumber':'310279617','incomeYear':2025},'ledgerEntries':[]}))
  env={'TALLI_ANNUAL_ACCOUNTS_APPROVED_TEST_WRITE':'true','TALLI_MASKINPORTEN_ENVIRONMENT':'test','TALLI_MASKINPORTEN_SCOPE':'altinn:instances.read altinn:instances.write','TALLI_MASKINPORTEN_SYSTEM_USER_ORG':'310279617','TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF':'synthetic','TALLI_ANNUAL_ACCOUNTS_CONTACT_EMAIL':'x@example.invalid','TALLI_ANNUAL_ACCOUNTS_APPROVAL_DATE':'2026-06-30','TALLI_ANNUAL_ACCOUNTS_CONFIRMING_REPRESENTATIVE':'Synthetic Person','TALLI_ANNUAL_ACCOUNTS_CASE_PATH':str(case),'TALLI_ANNUAL_ACCOUNTS_EVIDENCE_PATH':str(journal)}
  kwargs={'client_factory':connect,'generate':lambda *_:{'mainFormXml':'<main/>','companyAccountsXml':'<accounts/>','feedback':[]},'validate':lambda *_:None}
  with patch.object(local,'git_commit',lambda:'f1e6316c4cac895c43be88aef776c88cc97db204'),patch.object(local,'now',lambda:'2026-09-14T12:00:00.000Z'):
   first=asyncio.create_task(run(env,**kwargs))
   await asyncio.wait_for(ready.wait(),timeout=2)
   from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsAuthorityError
   try:
    try: await asyncio.wait_for(run(env,**kwargs),timeout=1)
    except AnnualAccountsAuthorityError as error:
     assert error.code=='ANNUAL_ACCOUNTS_REHEARSAL_IN_PROGRESS' and not error.retryable
    else: raise AssertionError('Second concurrent invocation was accepted')
    assert state['arrived']==1
   finally:
    release.set()
   results=[await asyncio.wait_for(first,timeout=2)]
  saved=json.loads(journal.read_text())
  assert state['creates']==state['locks']==1
  assert len({row['instanceId'] for row in results})==1
  print(json.dumps({'status':'EXCLUSIVE_OWNERSHIP_VERIFIED','sameRealEvidenceFile':True,'secondRejectedBeforeConnect':state['arrived']==1,'createEffects':state['creates'],'lockEffects':state['locks'],'returnedInstances':[x['instanceId'] for x in results],'persistedInstance':saved['instance']['id'],'returnedStatuses':[x['status'] for x in results],'mode':'ACTUAL_CLI_AND_LOCAL_FILE_IO_WITH_FAKE_PROVIDER','temporaryFilesRemovedAfterProbe':True},indent=2))
asyncio.run(main())
