"""Original real-file concurrency failure, rescheduled for rejection before connect."""
import asyncio,json,tempfile,os
from pathlib import Path
from unittest.mock import patch
from talli_backend.authority_tools.annual_accounts_test import run
from talli_backend.adapters import local_annual_accounts_rehearsal as local
from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsAuthorityError
from test_annual_accounts_rehearsal_ownership import environment,generated,Provider
PRIVATE=Path(__file__).parent
async def main():
 results=[]
 for alias in ('same_path','directory_alias','file_symlink'):
  with tempfile.TemporaryDirectory(prefix='journal-spec-',dir=PRIVATE) as folder:
   root=Path(folder);env=environment(root);first_connect=asyncio.Event();release=asyncio.Event();provider=Provider();connections=[]
   async def connect(*_):connections.append('connect');first_connect.set();await release.wait();return provider
   args={'client_factory':connect,'generate':generated,'validate':lambda *_:None}
   with patch.object(local,'git_commit',lambda:'f1e6316c4cac895c43be88aef776c88cc97db204'),patch.object(local,'now',lambda:'2026-09-14T12:00:00.000Z'):
    first=asyncio.create_task(run(env,**args));await asyncio.wait_for(first_connect.wait(),1)
    second_env=dict(env)
    if alias=='directory_alias':(root/'directory').symlink_to(root,target_is_directory=True);second_env['TALLI_ANNUAL_ACCOUNTS_EVIDENCE_PATH']=str(root/'directory/evidence.json')
    if alias=='file_symlink':(root/'file-alias.json').symlink_to(root/'evidence.json');second_env['TALLI_ANNUAL_ACCOUNTS_EVIDENCE_PATH']=str(root/'file-alias.json')
    try:
     try:await asyncio.wait_for(run(second_env,**args),1)
     except AnnualAccountsAuthorityError as e:assert e.code=='ANNUAL_ACCOUNTS_REHEARSAL_IN_PROGRESS';assert not e.retryable
     else:raise AssertionError('second run reached provider')
     assert len(connections)==1 and provider.creates==provider.locks==0
    finally:release.set();result=await first
    journal=root/'evidence.json';saved=json.loads(journal.read_text());sidecar=root/'.evidence.json.lock';inode=sidecar.stat().st_ino
    assert saved['instance']['id']==result['instanceId'] and provider.creates==provider.locks==1
    await run(env,**args)
    assert provider.creates==provider.locks==1 and sidecar.stat().st_ino==inode
    assert sidecar.stat().st_mode&0o777==0o600
    results.append({'case':alias,'rejectedBeforeSecondConnect':True,'createEffects':1,'lockEffects':1,'onlyReturnedInstancePersisted':True,'subsequentReadOnlyResume':True,'persistentSidecarInode':True})
 print(json.dumps({'status':'PASS','count':len(results),'cases':results,'limits':'Actual CLI/local files with fake provider and fixed clock/revision; no DB/provider/network.'},indent=2))
asyncio.run(main())
