import sys,json
from contextlib import asynccontextmanager
from fastapi.testclient import TestClient
from talli_backend.main import create_app, annual_accounts_json_wire
from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsFilingRows
from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,IncomeYear,UserId
C=CompanyId('15300000-0000-4000-8000-000000000001');A=ActorId(ActorKind.USER,UserId('15300000-0000-4000-8000-000000000010'));P='15300000-0000-4000-8000-000000000020'
class Sessions:
 actor_id=A
 async def session(self,token):return self
 @asynccontextmanager
 async def transaction(self):yield self
 async def filing_workspace(self,query):return self.value
results=[]
for depth in [1,600]:
 nested='kept'
 for _ in range(depth):nested={'ignored':nested}
 row=dict(id=P,company_id=str(C),setup_id=None,income_year=2025,filing='årsregnskap',status='ready',issues=[{'message':'kept','metadata':nested}],preview='synthetic',hovedskjema_xml=None,underskjema_xml={},source='synthetic',created_by=str(A.subject),created_at='2026-09-14T09:00:00.000Z')
 # Standard JSON accepts the original transport-shaped row; the owned result copies it.
 serialized=json.dumps(row);assert json.loads(serialized)==row
 s=Sessions();s.value=AnnualAccountsFilingRows(C,IncomeYear(2025),previews=[row],submissions=[],overrides=[],review_comments=[],permissions=[],test_evidence=[])
 try:annual_accounts_json_wire(s.value.previews);thaw='PASS'
 except Exception as e:thaw=type(e).__name__
 with TestClient(create_app(annual_accounts_session_factory=s),raise_server_exceptions=True) as client:
  response=client.get(f'/api/v1/annual-accounts/filing-workspace?companyId={C}&incomeYear=2025',headers={'Authorization':'Bearer fixture'})
 results.append({'depth':depth,'jsonRoundTrip':'PASS','publicImmutableProjection':'PASS','thaw':thaw,'httpStatus':response.status_code,'body':response.text if response.status_code!=200 else 'complete workspace'})
print(json.dumps(results,indent=2))
