"""Back up and remove only detached anonymous talli_test volumes from recorded gates."""
from pathlib import Path
from datetime import datetime
import gzip,hashlib,json,os,re,subprocess,tarfile
private=Path(__file__).parent;env={**os.environ,'DOCKER_HOST':'unix:///Users/kristianelmer/.colima/talli/docker.sock'}
windows=[('2026-09-14T04:14:00+00:00','2026-09-14T04:33:59+00:00'),('2026-09-14T04:35:00+00:00','2026-09-14T04:54:59+00:00'),('2026-09-14T05:23:50+00:00','2026-09-14T05:44:22+00:00')]
windows=[tuple(map(datetime.fromisoformat,pair)) for pair in windows]
ids=subprocess.check_output(['docker','volume','ls','--filter','dangling=true','-q'],env=env,text=True).splitlines()
inventory=json.loads(subprocess.check_output(['docker','volume','inspect',*ids],env=env,text=True))
candidates=[x for x in inventory if x.get('Labels')=={'com.docker.volume.anonymous':''} and re.fullmatch('[a-f0-9]{64}',x['Name']) and any(a<=datetime.fromisoformat(x['CreatedAt'])<=b for a,b in windows)]
probe="""import json,sys
from pathlib import Path
out=[]
for name in json.load(sys.stdin):
 p=Path('/mnt/lima-colima-talli/docker/volumes')/name/'_data'
 version=(p/'PG_VERSION').read_text().strip() if (p/'PG_VERSION').exists() else None
 catalog=p/'global/1262'
 out.append({'name':name,'version':version,'talliTestCatalog':catalog.exists() and b'talli_test' in catalog.read_bytes()})
print(json.dumps(out))
"""
proof=json.loads(subprocess.check_output(['colima','ssh','--profile','talli','--','sudo','python3','-c',probe],input=json.dumps([x['Name'] for x in candidates]),text=True))
selected=[x['name'] for x in proof if x['version'] in ('16','17') and x['talliTestCatalog']]
assert selected,'no proven test volumes'
backup=private/'owned-previous-gate-volumes.tar.gz'
assert not backup.exists()
with backup.open('xb') as out:
 os.chmod(backup,0o600)
 subprocess.run(['colima','ssh','--profile','talli','--','sudo','tar','-czf','-','-C','/mnt/lima-colima-talli/docker/volumes',*[n+'/_data' for n in selected]],stdout=out,check=True)
with tarfile.open(backup,'r:gz') as archive:
 names={entry.name.split('/')[0] for entry in archive.getmembers()}
 assert names==set(selected)
 for name in selected:assert archive.extractfile(name+'/_data/PG_VERSION').read().strip() in (b'16',b'17')
with backup.open('rb') as f:backup_sha=hashlib.file_digest(f,'sha256').hexdigest()
# Recheck immediately before deletion. Docker also refuses in-use volumes.
detached=set(subprocess.check_output(['docker','volume','ls','--filter','dangling=true','-q'],env=env,text=True).splitlines())
assert set(selected)<=detached
subprocess.run(['docker','volume','rm',*selected],env=env,check=True,stdout=subprocess.DEVNULL)
report={'status':'PASS','scope':'detached anonymous talli_test volumes created during recorded #152/#153 gate windows','selectedMetadata':[x for x in candidates if x['Name'] in selected],'catalogProof':proof,'backup':str(backup),'backupSha256':backup_sha,'backupBytes':backup.stat().st_size,'removedCount':len(selected),'retained': 'all active volumes, named volumes, unmatched creation windows and volumes without talli_test marker'}
(private/'owned-gate-disk-recovery.json').write_text(json.dumps(report,indent=2)+'\n')
print('Backed up and removed',len(selected),'proven prior-gate test volumes; backup bytes',backup.stat().st_size,'SHA256',backup_sha)
