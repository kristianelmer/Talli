"""Two simultaneous calls sharing one logical durable journal; fake provider only."""
import asyncio,copy,json
from test_annual_accounts_rehearsal_recovery import EvidenceIO,CONFIG
from talli_backend.modules.annual_accounts_filing.public import rehearse_annual_accounts
async def main():
 state={'saved':None,'arrived':0,'creates':0};ready=asyncio.Event()
 class SharedIO(EvidenceIO):
  def __init__(self):super().__init__('never','none')
  def load_evidence(self):return copy.deepcopy(state['saved'])
  def save_evidence(self,value):state['saved']=copy.deepcopy(value)
  async def connect(self,*_):
   state['arrived']+=1
   if state['arrived']==2:ready.set()
   await ready.wait()
   return self
  async def create_instance(self,**_):
   state['creates']+=1
   return {'id':f'instance-{state["creates"]}','dataIds':{'mainForm':'main','companyAccounts':'accounts'},'processTask':'data'}
 results=await asyncio.gather(rehearse_annual_accounts(CONFIG,SharedIO()),rehearse_annual_accounts(CONFIG,SharedIO()))
 print(json.dumps({'sameJournal':'in-memory-evidence.json','createEffects':state['creates'],'returnedInstances':[x['instanceId'] for x in results],'persistedInstance':state['saved']['instance']['id'],'returnedStatuses':[x['status'] for x in results],'mode':'LOCAL_FAKE_NO_DB_OR_PROVIDER'},indent=2))
asyncio.run(main())
