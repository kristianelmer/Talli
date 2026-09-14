"""Real local PostgREST legacy table protocol and FastAPI/SQL phase matrix.
Fixture JWT/verified claims; real Auth/TOTP is a separate browser lane.
"""
from pathlib import Path
import base64,hashlib,hmac,json,os,subprocess,sys,time
from uuid import uuid4
import httpx,psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from fastapi.testclient import TestClient
root=Path.cwd();private=Path(__file__).parent
sys.path[:0]=[str(root/'apps/backend/src'),str(root/'apps/backend/tests')]
from test_annual_accounts_filing_lifecycle import apply,EXPANSION,CUTOVER,CONTRACT,COMPANY,memberships
from accounts_database_fixtures import seed,ACTORS
from talli_backend.adapters.postgres_annual_accounts import PostgresAnnualAccountsSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.main import create_app
from talli_backend.shared.kernel import ActorId,ActorKind,UserId
source=conninfo_to_dict(json.loads((private/'expand-fix-clone-private-04e682b6.json').read_text())['DB_URL'])
assert source['host'] in ('localhost','127.0.0.1') and source['port']=='52966' and source['dbname']=='accounts153_setup_fix_d060'
target='accounts153_protocol_eb7d3120';container='talli-accounts153-protocol-eb7d3120'
env={**os.environ,'DOCKER_HOST':'unix:///Users/kristianelmer/.colima/talli/docker.sock'}
def docker(args):return subprocess.run(['docker',*args],env=env,capture_output=True,check=True).stdout
admin=psycopg.connect(make_conninfo(**{**source,'dbname':'postgres'}),autocommit=True)
prior=memberships(admin);created=False;web_started=False;roles=[];client=None;checks=[]
web_role='accounts153_web_'+uuid4().hex;api_role='accounts153_api_'+uuid4().hex
password=uuid4().hex;secret=uuid4().hex+uuid4().hex
config=private/'accounts153-protocol-private.env'
url=make_conninfo(**{**source,'dbname':target})
def migrate(name,rollback=False):
 with psycopg.connect(url,autocommit=True) as db:
  db.execute('begin');apply(db,name,rollback=rollback);db.execute('commit')
  db.execute("notify pgrst,'reload schema'")
 time.sleep(.35)
def record(label):checks.append(label);print('PASS',label,flush=True)
try:
 assert not admin.execute('select 1 from pg_database where datname=%s',(target,)).fetchone()
 admin.execute(sql.SQL('create database {} template {}').format(sql.Identifier(target),sql.Identifier(source['dbname'])));created=True
 with psycopg.connect(url) as db:
  seed(db)
  for role,granted in ((web_role,'authenticated'),(api_role,'annual_accounts_filing_workflow_executor')):
   db.execute(sql.SQL('create role {} login noinherit nobypassrls password {}').format(sql.Identifier(role),sql.Literal(password)))
   db.execute(sql.SQL('grant {} to {} with admin false,inherit false,set true').format(sql.Identifier(granted),sql.Identifier(role)))
   roles.append(role)
 claims={'sub':ACTORS['owner'],'role':'authenticated','aal':'aal2','amr':[{'method':'totp','timestamp':int(time.time())}],'exp':int(time.time())+3600}
 b64=lambda data:base64.urlsafe_b64encode(data).rstrip(b'=')
 unsigned=b64(json.dumps({'alg':'HS256','typ':'JWT'}).encode())+b'.'+b64(json.dumps(claims).encode())
 token=(unsigned+b'.'+b64(hmac.new(secret.encode(),unsigned,hashlib.sha256).digest())).decode()
 networks=json.loads(docker(['inspect','supabase_db_tallig6753','--format','{{json .NetworkSettings.Networks}}']))
 assert len(networks)==1
 config.write_text(f'PGRST_DB_URI=postgresql://{web_role}:{password}@supabase_db_tallig6753:5432/{target}\nPGRST_DB_SCHEMAS=public\nPGRST_DB_ANON_ROLE={web_role}\nPGRST_JWT_SECRET={secret}\n');config.chmod(0o600)
 docker(['run','--detach','--name',container,'--label','talli.fixture=accounts153-protocol','--network',next(iter(networks)),'--publish','127.0.0.1::3000','--env-file',str(config),'public.ecr.aws/supabase/postgrest:v14.14']);web_started=True
 endpoint='http://'+docker(['port',container,'3000/tcp']).decode().strip();assert endpoint.startswith('http://127.0.0.1:')
 headers={'authorization':'Bearer '+token,'prefer':'return=representation'}
 for _ in range(80):
  try:
   if httpx.get(endpoint,headers=headers).status_code==200:break
  except httpx.HTTPError:pass
  time.sleep(.1)
 else:raise AssertionError('PostgREST did not start')
 verified=_VerifiedActor(ActorId(ActorKind.USER,UserId(ACTORS['owner'])),json.dumps(claims))
 api_url=make_conninfo(url,user=api_role,password=password)
 class Sessions:
  async def session(self,received):
   assert received=='fixture';return PostgresAnnualAccountsSession(api_url,verified)
 client=TestClient(create_app(annual_accounts_session_factory=Sessions()))
 case=json.loads((root/'architecture/evidence/issues/153/characterization/legacy-pure-characterization.json').read_text())['evidenceCases'][0]
 evidence=json.loads(json.dumps(case['input']['evidence']).replace(case['input']['expectedCompanyOrgNumber'],'000000153'))
 def new():return client.post('/api/v1/annual-accounts/tt02-evidence-imports',headers={'Authorization':'Bearer fixture'},json={'companyId':COMPANY,'evidenceJson':json.dumps(evidence),'evidenceUrl':None})
 def workspace():return client.get('/api/v1/annual-accounts/filing-workspace',headers={'Authorization':'Bearer fixture'},params={'companyId':COMPANY,'incomeYear':2025})
 def old():return httpx.post(endpoint+'/authority_test_runs',headers=headers,json={'company_id':COMPANY,'obligation':'aarsregnskap','status':'pending','test_reference':'synthetic-deployment-'+uuid4().hex,'recorded_by':ACTORS['owner']})
 def current_unavailable(label):
  for r in (new(),workspace()):assert r.status_code==503,(label,r.status_code,r.text)
  record(label)
 def old_success(label):
  r=old();assert r.status_code==201,(r.status_code,r.text);record(label);return r.json()[0]['id']
 def old_denied(label):
  r=old();assert r.status_code in (400,401,403,404),(r.status_code,r.text);record(label)
 def new_success(label):
  r=new();assert r.status_code==200,(r.status_code,r.text);record(label);return r.json()['recordId']
 def includes(ids,label):
  r=workspace();assert r.status_code==200,(r.status_code,r.text)
  actual={v['id'] for v in r.json()['testEvidence']};assert set(ids)<=actual;record(label)
 current_unavailable('new API on predecessor storage unavailable')
 first=old_success('legacy REST remains original writer')
 for name in EXPANSION:migrate(name)
 current_unavailable('new API on inactive expansion unavailable')
 second=old_success('legacy REST still writes during expansion')
 migrate(CUTOVER)
 old_denied('legacy REST writes fenced after cutover')
 third=new_success('current API imports pending evidence after cutover')
 includes([first,second,third],'current API reads pre-cutover and current evidence')
 migrate(CONTRACT)
 old_denied('legacy REST absent after physical contract')
 fourth=new_success('current API writes after physical contract')
 includes([first,second,third,fourth],'contract preserves all four evidence generations')
 migrate(CONTRACT,True)
 old_denied('contract rollback retains fenced legacy writer')
 includes([third,fourth],'contract rollback retains current reads')
 migrate(CUTOVER,True)
 current_unavailable('current API unavailable after full rollback')
 fifth=old_success('full rollback restores legacy REST writer')
 r=httpx.get(endpoint+'/authority_test_runs',headers=headers,params={'select':'id','company_id':'eq.'+COMPANY});assert r.status_code==200,r.text
 assert {first,second,third,fourth,fifth}<={v['id'] for v in r.json()};record('legacy REST reads latest owned evidence after rollback')
 migrate(CUTOVER);migrate(CONTRACT)
 old_denied('legacy REST fenced again after recutover')
 includes([first,second,third,fourth,fifth],'recutover preserves all five evidence generations')
finally:
 if client:client.close()
 if web_started:docker(['rm','--force','--volumes',container])
 if config.exists():config.unlink()
 if created:
  assert not admin.execute('select 1 from pg_stat_activity where datname=%s',(target,)).fetchone()
  admin.execute(sql.SQL('drop database {}').format(sql.Identifier(target)))
 for role in roles:admin.execute(sql.SQL('drop role {}').format(sql.Identifier(role)))
 assert memberships(admin)==prior
 admin.close()
(private/'accounts-deployment-order.json').write_text(json.dumps({'status':'PASS','checks':checks,'count':len(checks),'sourceRevision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'limits':'Fixture JWT realm and injected verified session; actual PostgREST, FastAPI ASGI and restricted SQL adapter. Real Auth/TOTP is separate browser evidence.','cleanup':'Owned container/database/ephemeral logins removed, all global memberships restored','providerCalls':0,'hostedChanges':0},indent=2)+'\n')
