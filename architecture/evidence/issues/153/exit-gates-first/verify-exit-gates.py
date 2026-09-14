"""Read-only root verification of produced complete gate receipts."""
import hashlib,json,subprocess,sys
from datetime import datetime
from pathlib import Path
expected=['credential-scan','typecheck','architecture','boundary','build-web','build-backend','boundary-smoke','launch-rehearsal','production-dependency-audit','database-isolation','whitespace']
sha=lambda v:'sha256:'+hashlib.sha256(v).hexdigest()
verified=[]
for rev in sys.argv[1:]:
 path=Path('architecture/evidence/customer-ready-gates')/(rev+'.json')
 e=json.loads(path.read_text());t=Path(e['transcriptPath']).read_bytes();s=t.decode()
 assert e['revision']==rev and e['verdict']=='pass'
 assert [x['name'] for x in e['checks']]==expected
 assert all(x['exitCode']==0 and x['durationMs']>=0 for x in e['checks'])
 assert e['transcriptDigest']==sha(t)
 assert e['producerDigest']==sha(subprocess.check_output(['git','show',rev+':'+e['producer']]))
 assert s.startswith('customer-ready-release-gate revision='+rev+'\n') and s.endswith('verdict=pass\n')
 for x in e['checks']:
  assert s.count('['+x['name']+'] exit=0\n')==1
  assert '['+x['name']+'] durationMs='+str(x['durationMs'])+'\n' in s
 start=datetime.fromisoformat(e['startedAt'].replace('Z','+00:00'));end=datetime.fromisoformat(e['executedAt'].replace('Z','+00:00'));assert start<end
 if verified:
  assert e['previousPassingRevision']==verified[-1]['revision']
  assert verified[-1]['executedAt']<e['startedAt']
  subprocess.run(['git','merge-base','--is-ancestor',verified[-1]['revision'],rev],check=True)
 verified.append({'revision':rev,'canonicalDigest':sha(json.dumps(e,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()),'transcriptDigest':e['transcriptDigest'],'producerDigest':e['producerDigest'],'startedAt':e['startedAt'],'executedAt':e['executedAt'],'checkCount':len(e['checks']),'previousPassingRevision':e['previousPassingRevision']})
print(json.dumps({'status':'PASS_ROOT_COMPLETE_GATE_VERIFICATION','gates':verified},indent=2))
