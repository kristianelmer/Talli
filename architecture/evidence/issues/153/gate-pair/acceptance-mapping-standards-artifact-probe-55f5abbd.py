"""Read-only current/historical SHA bindings; no gate or runtime certification."""
from pathlib import Path
import hashlib,json,subprocess,sys
repo,root,output=map(Path,sys.argv[1:]); candidate='55f5abbdcb0f4d638f26aea093db13722ef922c5'; baseline='5b74340ca75f215b43d754c6bf0fc49ef5974b0b'
def git(*args):return subprocess.check_output(['git',*args],cwd=repo)
def sha(b):return hashlib.sha256(b).hexdigest()
e=root/'architecture/evidence/issues/153';bindings=[];history={};unresolved=[]
for manifest in sorted(e.glob('*/manifest.json')):
 data=json.loads(manifest.read_text())
 items=data['artifacts']
 if isinstance(items,list):
  items={str((root/x['path'] if (root/x['path']).exists() else manifest.parent/x['path']).relative_to(root)):x['sha256'] for x in items}
 for name,want in items.items():
  if not isinstance(want,str):
   unresolved.append({'manifest':str(manifest.relative_to(root)),'path':name,'expected':want,'reason':'non-string schema'});continue
  path=root/name
  if path.exists() and sha(path.read_bytes())==want:revision=candidate
  else:
   if name not in history:
    history[name]={}
    for commit in git('log','--format=%H',candidate,'--',name).decode().splitlines():
     raw=subprocess.run(['git','show',commit+':'+name],cwd=repo,capture_output=True)
     if raw.returncode==0:history[name].setdefault(sha(raw.stdout),commit)
   revision=history[name].get(want)
  row={'manifest':str(manifest.relative_to(root)),'path':name,'sha256':want,'verifiedAtRevision':revision}
  bindings.append(row)
  if revision is None:unresolved.append(row)
x=json.loads((e/'dependency-integration/manifest.json').read_text())['publicationRedactions'][0]
old=Path(x['originalPrivatePath']).read_bytes(); new=(root/x['artifact']).read_bytes()
assert sha(old)==x['originalSha256'] and git('show',x['originalRevision']+':'+x['artifact'])==old
marker=b'BEGIN PRIVATE KEY';replacement=b'[REDACTED SYNTHETIC TEST KEY HEADER]'
assert old.count(marker)==x['occurrences']==4 and old.replace(marker,replacement)==new
x2=json.loads((e/'publication-follow-up/manifest.json').read_text())['originalFailedGate']; old2=Path(x2['privatePath']).read_bytes();new2=(e/'publication-follow-up'/x2['publishedDerivative']).read_bytes()
assert sha(old2)==x2['sha256'] and old2.replace(marker,replacement)==new2
assert git('diff','--name-only',baseline+'...'+candidate,'--','scripts/check-committed-credentials.mjs','tests/committed_credentials.test.mjs')==b''
source=json.loads((e/'source-inventory.json').read_text()); entry=[]
for name,info in source['sourceFiles'].items():
 assert sha(git('show',baseline+':'+name))==info['baselineSha256'];entry.append(name)
result={'candidate':candidate,'baseline':baseline,'manifestCount':len(list(e.glob('*/manifest.json'))),'bindings':bindings,'unresolved':unresolved,'sourceInventoryVerified':len(entry),'redactions':{'rehearsalExactOnlyMarkerReplacements':old.count(marker),'failedGateExactOnlyMarkerReplacements':old2.count(marker),'originalPrivateAndPriorCommitPreserved':True,'credentialScannerUnchanged':True}}
output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='bindings'},indent=2))
