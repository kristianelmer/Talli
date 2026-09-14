"""Current generated Accounts consumer against exact predecessor FastAPI HTTP."""
import hashlib,json,os,socket,subprocess,time
from pathlib import Path
import httpx
root=Path.cwd();private=Path(__file__).parent;base='5b74340ca75f215b43d754c6bf0fc49ef5974b0b';archive=private/'old-backend-5b-accounts-protocol';archive.mkdir()
raw=subprocess.check_output(['git','archive',base,'apps/backend/src'])
subprocess.run(['tar','-x','-C',str(archive)],input=raw,check=True)
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
env={**os.environ,'PYTHONPATH':str(archive/'apps/backend/src')}
for key in list(env):
 if key.startswith(('SUPABASE_','TALLI_','NEXT_PUBLIC_')):env.pop(key)
log=(private/'accounts-old-backend-server.log').open('w')
server=subprocess.Popen([str(root/'apps/backend/.venv/bin/python'),'-m','uvicorn','talli_backend.main:create_app','--factory','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=archive,env=env,stdout=log,stderr=subprocess.STDOUT)
try:
 origin=f'http://127.0.0.1:{port}'
 for _ in range(100):
  assert server.poll() is None,'predecessor server stopped'
  try:
   if httpx.get(origin+'/openapi.json').status_code==200:break
  except httpx.HTTPError:pass
  time.sleep(.1)
 else:raise AssertionError('predecessor server unavailable')
 transport=(root/'apps/web/features/annual-accounts-filing/transport.ts').as_uri()
 source=(root/'apps/web/app/lib/annual-accounts-workspace-source.ts').as_uri()
 code='''import assert from 'node:assert/strict';
const t=await import(TRANSPORT);const {loadPresentedAnnualAccountsSource}=await import(SOURCE);
const company='15300000-0000-4000-8000-000000000001';
const calls=[()=>t.loadAnnualAccountsFilingWorkspace('fixture',company,2025),
()=>t.loadAnnualAccountsSourceFacts('fixture',company,2025),
()=>t.importAnnualAccountsTt02Evidence('fixture',{companyId:company,evidenceJson:'{}',evidenceUrl:null}),
()=>t.findAnnualAccountsPreview('fixture',company),
()=>t.acknowledgeOwnedAnnualAccountsComment('fixture',company)];
for (const call of calls) {
 let failure;try {await call();} catch(error) {failure=error;}
 assert.ok(failure,'missing route cannot become a successful empty result');assert.equal(failure.status,404);
 assert.equal(t.annualAccountsEvidenceImportErrorMessage(failure),'TT02-evidensen kunne ikke lagres.');
 assert.equal(t.annualAccountsActionErrorMessage(failure),'Årsregnskapet kunne ikke oppdateres. Prøv igjen.');
}
const result=await loadPresentedAnnualAccountsSource('fixture',[company],2025);
assert.equal(result.error,'Årsregnskapsgrunnlaget kunne ikke leses. Prøv igjen.');
assert.deepEqual(result.submissions,[]);console.log('PASS five real predecessor HTTP 404 rejections and unavailable workspace composition');
'''.replace('TRANSPORT',json.dumps(transport)).replace('SOURCE',json.dumps(source))
 (private/'accounts-old-backend-consumer.mjs').write_text(code)
 node='/Users/kristianelmer/.codex/issue-192-private/runtime/node-v24.20.0-darwin-arm64/bin/node'
 consumer=subprocess.run([node,'--experimental-strip-types',str(private/'accounts-old-backend-consumer.mjs')],env={**os.environ,'TALLI_BACKEND_URL':origin},capture_output=True,text=True)
 (private/'accounts-old-backend-consumer.log').write_text(consumer.stdout+consumer.stderr)
 assert consumer.returncode==0,'current consumer failed; inspect private log'
 report={'status':'PASS','predecessorRevision':base,'predecessorArchiveSha256':hashlib.sha256(raw).hexdigest(),'currentRevision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'checks':['workspace rejects raw missing route','source facts reject raw missing route','import rejects raw missing route','preview lookup does not translate raw404 into not found','acknowledgement does not translate raw404 into not found','all raw404s map to unavailable Norwegian errors','workspace composition retains error instead of successful empty history'],'currentConsumerSha256':hashlib.sha256(code.encode()).hexdigest(),'sourceBindings':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [root/'apps/web/features/annual-accounts-filing/transport.ts',root/'apps/web/app/lib/annual-accounts-workspace-source.ts']},'effects':'No DB or provider configuration, no external operations; predecessor HTTP server stopped'}
 (private/'accounts-old-backend-protocol.json').write_text(json.dumps(report,indent=2)+'\n')
 print('PASS',len(report['checks']),'old-backend deployment checks')
finally:
 server.terminate();server.wait(timeout=10);log.close()
