"""Actual CLI run + actual local JSON journal; only provider/clock/XML are fake."""
import asyncio,json,tempfile
from pathlib import Path
from unittest.mock import patch
from talli_backend.authority_tools.annual_accounts_test import run
from talli_backend.adapters import local_annual_accounts_rehearsal as local
async def main():
 ready=asyncio.Event();state={'arrived':0,'creates':0,'locks':0}
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
  if state['arrived']==2:ready.set()
  await ready.wait()
  return Client()
 with tempfile.TemporaryDirectory(prefix='accounts153-concurrent-cli-') as directory:
  case=Path(directory)/'case.json';journal=Path(directory)/'evidence.json'
  case.write_text(json.dumps({'synthetic':True,'environment':'test','company':{'orgNumber':'310279617','incomeYear':2025},'ledgerEntries':[]}))
  env={'TALLI_ANNUAL_ACCOUNTS_APPROVED_TEST_WRITE':'true','TALLI_MASKINPORTEN_ENVIRONMENT':'test','TALLI_MASKINPORTEN_SCOPE':'altinn:instances.read altinn:instances.write','TALLI_MASKINPORTEN_SYSTEM_USER_ORG':'310279617','TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF':'synthetic','TALLI_ANNUAL_ACCOUNTS_CONTACT_EMAIL':'x@example.invalid','TALLI_ANNUAL_ACCOUNTS_APPROVAL_DATE':'2026-06-30','TALLI_ANNUAL_ACCOUNTS_CONFIRMING_REPRESENTATIVE':'Synthetic Person','TALLI_ANNUAL_ACCOUNTS_CASE_PATH':str(case),'TALLI_ANNUAL_ACCOUNTS_EVIDENCE_PATH':str(journal)}
  kwargs={'client_factory':connect,'generate':lambda *_:{'mainFormXml':'<main/>','companyAccountsXml':'<accounts/>','feedback':[]},'validate':lambda *_:None}
  with patch.object(local,'git_commit',lambda:'10e6698efdcad2726f5ca9f7dcdb7352317ceb11'),patch.object(local,'now',lambda:'2026-09-14T12:00:00.000Z'):
   results=await asyncio.gather(run(env,**kwargs),run(env,**kwargs))
  saved=json.loads(journal.read_text())
  assert state['creates']==state['locks']==2
  assert len({row['instanceId'] for row in results})==2
  print(json.dumps({'status':'DUPLICATE_EFFECT_REPRODUCED','sameRealEvidenceFile':True,'createEffects':state['creates'],'lockEffects':state['locks'],'returnedInstances':[x['instanceId'] for x in results],'persistedInstance':saved['instance']['id'],'returnedStatuses':[x['status'] for x in results],'mode':'ACTUAL_CLI_AND_LOCAL_FILE_IO_WITH_FAKE_PROVIDER','temporaryFilesRemovedAfterProbe':True},indent=2))
asyncio.run(main())
