from pathlib import Path
import json,os,subprocess,sys
from urllib.parse import quote
from psycopg.conninfo import conninfo_to_dict
p=Path('/Users/kristianelmer/.codex/issue-192-private/issue153-entry');c=conninfo_to_dict(json.loads((p/'lifecycle-private.json').read_text())['DB_URL'])
assert c['host'] in ('localhost','127.0.0.1') and c['port']=='52966' and c['dbname']=='accounts153_lifecycle_d060'
uri='postgresql://'+quote(c['user'],safe='')+':'+quote(c.get('password',''),safe='')+'@'+c['host']+':'+c['port']+'/'+quote(c['dbname'],safe='')+'?sslmode=disable'
env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','LANG','TMPDIR')}
r=subprocess.run(['node_modules/.bin/supabase','db','advisors','--db-url',uri,'--output','json','--debug'],env=env,capture_output=True,text=True)
for name,raw in [('stdout',r.stdout),('stderr',r.stderr)]:
 raw=raw.replace(uri,'<LOCAL_DATABASE_URI>').replace(c.get('password','') or '<NONE>','<REDACTED>')
 (p/('expand-advisors-local-tls.'+name)).write_text(raw)
print(json.dumps({'exit':r.returncode,'stdoutBytes':len(r.stdout),'stderrBytes':len(r.stderr)}))
if r.returncode:sys.exit(r.returncode)
findings=json.loads(r.stdout)
blocking=[f for f in findings if f.get('level')=='ERROR' or f.get('facing')=='EXTERNAL' and 'SECURITY' in f.get('categories',[])]
summary={'database':c['dbname'],'findings':len(findings),'blocking':len(blocking),'accountsFindings':[f for f in findings if 'annual_accounts' in json.dumps(f)],'status':'PASS' if not blocking else 'FAIL'}
(p/'expand-advisors-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
if blocking:sys.exit(1)
