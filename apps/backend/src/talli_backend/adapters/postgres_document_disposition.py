"""Documents disposition for an explicitly registered, disposable native target.

No production composition or admin-DSN fallback. Docker ownership, internal-only
upstreams and the actual host PostgreSQL session are checked before every SQL
operation. Registration is a separate local operator action; only its synthetic
allowlist can be erased. Storage API retirement precedes checked local historical
file cleanup. Neither unlink nor native DELETE is forensic media erasure.
"""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json
from pathlib import PurePosixPath
import re
import subprocess
from uuid import UUID, uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from talli_backend.modules.documents.public import (
    DocumentDispositionStore, document_disposition_adapter,
)


def native_document_generation(row, files):
    return sha256(json.dumps({'row':row,'files':files},sort_keys=True,separators=(',',':')).encode()).hexdigest()


# Runs in the exact owned Storage process. Credentials stay inside that process;
# no key is returned or sent through the published user ingress.
_STORAGE = r"""
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const input=JSON.parse(fs.readFileSync(0,'utf8'));const root='/mnt';
function manifest(){const rows=[];function walk(rel){const file=path.join(root,rel),s=fs.lstatSync(file);if(s.isSymbolicLink())throw Error('symlink');if(s.isDirectory()){for(const n of fs.readdirSync(file).sort())walk(path.posix.join(rel,n));}else{if(!s.isFile())throw Error('unsupported');const b=fs.readFileSync(file);rows.push({path:rel,bytes:b.length,sha256:crypto.createHash('sha256').update(b).digest('hex')});}}walk('.');return rows;}
(async()=>{
 if(input.action==='manifest'){process.stdout.write(JSON.stringify(manifest()));return;}
 if(input.action==='inventory'){
  if(!Array.isArray(input.keys)||!input.keys.length||input.keys.length>256||new Set(input.keys).size!==input.keys.length)throw Error('inventory bound');
  const objects={};const files=manifest();
  await Promise.all(input.keys.map(async key=>{
   if(typeof key!=='string'||key.length>1024||key.split('/').includes('..'))throw Error('invalid approved key');
   const response=await fetch('http://127.0.0.1:5000/object/info/authenticated/company-documents/'+key.split('/').map(encodeURIComponent).join('/'),{headers:{Authorization:'Bearer '+process.env.SERVICE_KEY,apikey:process.env.SERVICE_KEY},redirect:'error',signal:AbortSignal.timeout(5000)});
   const raw=await response.text();if(raw.length>65536)throw Error('response bound');objects[key]={status:response.status,body:raw};
  }));
  process.stdout.write(JSON.stringify({files,objects}));return;
 }
 if(input.action==='gc'){
  const approved=new Map(input.files.map(f=>[f.path,f]));
  const observed=manifest().filter(f=>f.path.startsWith(input.prefix));
  for(const f of observed){const a=approved.get(f.path);if(!a||a.bytes!==f.bytes||a.sha256!==f.sha256)throw Error('changed generation');}
  for(const f of observed)fs.unlinkSync(path.join(root,f.path));
  process.stdout.write('{}');return;
 }
 const response=await fetch('http://127.0.0.1:5000'+input.path,{method:input.method,headers:{Authorization:'Bearer '+process.env.SERVICE_KEY,apikey:process.env.SERVICE_KEY,'Content-Type':'application/json'},body:input.body===undefined?undefined:JSON.stringify(input.body),redirect:'error',signal:AbortSignal.timeout(5000)});
 const raw=await response.text();if(raw.length>65536)throw Error('response bound');
 process.stdout.write(JSON.stringify({status:response.status,body:raw}));
})().catch(()=>{process.stderr.write('owned storage observation failed');process.exit(1);});
"""


def _storage_presence(response, version):
    try:
        body=json.loads(response['body'])
        if response['status']==200 and isinstance(body,dict) and body.get('version')==version:
            return True
        # Pinned Storage v1 returns this exact documented-in-probe not_found
        # envelope as HTTP400. No other client/server error means absence.
        if response['status'] in {400,404} and body=={
            'statusCode':'404','error':'not_found','message':'Object not found'}:
            return False
    except (KeyError,TypeError,ValueError):
        pass
    raise ValueError('native_storage_observation_unavailable')


class OwnedNativeDocumentsTarget:
    """Explicit local construction handle; never discovers a hosted target."""
    def __init__(self, *, docker, nonce, label, database, storage, network,
                 database_image, storage_image, target, database_url):
        self.docker=docker
        self.nonce=UUID(nonce).hex
        self.target=str(UUID(target))
        if UUID(target).hex!=self.nonce:
            raise ValueError('native_target_identity')
        if label not in {'talli.native.disposition','talli.rf.identity.restore'}:
            raise ValueError('native_target_label')
        self.label=label;self.database=database;self.storage=storage;self.network=network
        self.images=(database_image,storage_image);self.database_url=database_url
        info=conninfo_to_dict(database_url)
        if (info.get('host')!='127.0.0.1' or info.get('hostaddr') not in (None,'127.0.0.1')
                or info.get('dbname')!='postgres' or not info.get('password')
                or not re.fullmatch(r'talli_native_disposition_[a-f0-9]{16,32}',info.get('user',''))
                or any(key in info for key in ('service','passfile','options'))):
            raise ValueError('native_operator_connection')
        self.login=info['user']
        self._source_connection=ContextVar('native_disposition_source_connection',default=None)
        self.system=self._query("select system_identifier::text from pg_control_system();").strip().decode()
        self.validate()

    def _run(self,*args,data=None):
        result=subprocess.run([self.docker,'--context','default',*args],input=data,capture_output=True,timeout=12,
                              env={'PATH':'/usr/local/bin:/usr/bin:/bin','DOCKER_HOST':'unix:///var/run/docker.sock'})
        if result.returncode:
            raise ValueError('native_target_control_unavailable')
        return result.stdout

    def _query(self,statement):
        return self._run('exec','-i',self.database,'psql','-h','/tmp','-U','supabase_admin','-d','postgres',
                         '-XqAt','-v','ON_ERROR_STOP=1',data=statement.encode())

    def validate(self):
        context=json.loads(self._run('context','inspect','default'))
        if len(context)!=1 or context[0]['Endpoints']['docker']['Host']!='unix:///var/run/docker.sock':
            raise ValueError('native_docker_context')
        network=json.loads(self._run('network','inspect',self.network))[0]
        if not network.get('Internal') or network.get('Labels',{}).get(self.label)!=self.nonce:
            raise ValueError('native_internal_network')
        for identifier,image in zip((self.database,self.storage),self.images,strict=True):
            row=json.loads(self._run('inspect',identifier))[0]
            if (row['Id']!=identifier or row['Image']!=image or not row['State']['Running']
                    or row['Config'].get('Labels',{}).get(self.label)!=self.nonce
                    or set(row['NetworkSettings']['Networks'])!={self.network}
                    or any(row['NetworkSettings']['Ports'].values())):
                raise ValueError('native_upstream_binding')
        if self._query('select system_identifier::text from pg_control_system();').strip().decode()!=self.system:
            raise ValueError('native_database_replaced')

    @contextmanager
    def connection(self):
        self.validate()
        bound=self._source_connection.get()
        if bound is not None:
            with bound.transaction():
                bound.execute('set local role documents_disposition_executor')
                bound.execute("set local lock_timeout='3s'")
                bound.execute("set local statement_timeout='5s'")
                yield bound
            return
        marker='native_disposition_'+uuid4().hex
        with psycopg.connect(self.database_url,connect_timeout=3,application_name=marker,row_factory=dict_row) as db:
            pid=db.execute('select pg_backend_pid() as pid').fetchone()['pid']
            statement=("select count(*) from pg_stat_activity where datname='postgres' and usename='"+self.login+
                       "' and pid="+str(int(pid))+" and application_name='"+marker+"';")
            if self._query(statement).strip()!=b'1':
                raise ValueError('native_operator_session_unbound')
            attributes=db.execute('select rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolinherit from pg_roles where rolname=session_user').fetchone()
            if any(attributes.values()):
                raise ValueError('native_operator_elevated')
            db.execute('set local role documents_disposition_executor')
            db.execute("set local lock_timeout='3s'")
            db.execute("set local statement_timeout='5s'")
            yield db

    @contextmanager
    def source_fence(self, company_id):
        """Same-session company write fence across independently durable phases.

        Native prepare/finalize take the same advisory key. Reusing this checked
        connection avoids a second session deadlocking against our own lease.
        ContextVar propagates to the sequential owner calls in asyncio.to_thread.
        """
        if self._source_connection.get() is not None:
            raise ValueError('native_disposition_nested_source_fence')
        with self.connection() as db:
            db.execute('select pg_advisory_lock(hashtextextended(%s,157))',(str(UUID(str(company_id))),))
            db.commit()
            token=self._source_connection.set(db)
            try:
                yield
            finally:
                self._source_connection.reset(token)
                db.rollback()
                db.execute('select pg_advisory_unlock(hashtextextended(%s,157))',(str(company_id),))
                db.commit()

    def objects(self,**request):
        self.validate()
        return json.loads(self._run('exec','-i',self.storage,'node','-e',_STORAGE,data=json.dumps(request).encode()))


@document_disposition_adapter(DocumentDispositionStore)
class PostgresDocumentDisposition(DocumentDispositionStore):
    def __init__(self, target: OwnedNativeDocumentsTarget):
        self.target=target

    def _call(self,phase,command):
        if phase not in {'state','prepare','storage_retired','finalize'}:
            raise ValueError('native_disposition_phase')
        with self.target.connection() as db:
            params=(self.target.target,self.target.system,command.operation_id,command.plan_sha256)
            if phase!='state':params+= (command.document_id,)
            markers=','.join(['%s']*len(params))
            row=db.execute('select documents.local_native_disposition_'+phase+'_v1('+markers+') as value',params).fetchone()
            return row['value']

    def _state(self,command):
        value=self._call('state',command);key=str(command.document_id)
        if (value['companyId']!=str(command.company_id) or value['generation']!=command.company_generation
                or key not in value['snapshot'] or key not in value['objects']):
            raise ValueError('native_disposition_command_changed')
        expected=dict(value['snapshot'])
        for erased,receipt in value['receipts'].items():
            if (receipt['plan_sha256']!=command.plan_sha256 or erased not in value['fixtureRecords']
                    or receipt['state'] not in {'prepared','storage_retired','erased'}):
                raise ValueError('native_disposition_receipt_changed')
            if receipt['state']=='erased':expected.pop(erased,None)
        if expected!=value['actual']:
            raise ValueError('native_disposition_metadata_changed')
        row=value['snapshot'][key];objects=value['objects'][key];files=objects['files']
        if (row['company_id']!=str(command.company_id) or row['income_year']!=command.income_year
                or row['content_sha256']!=command.content_sha256
                or native_document_generation(row,files)!=command.generation
                or objects['storageKey']!=row['storage_key']):
            raise ValueError('native_disposition_generation_changed')
        expected_key=str(command.company_id)+'/'+str(command.income_year)+'/'+str(command.document_id)+'/'
        if (not row['storage_key'].startswith(expected_key) or '..' in PurePosixPath(row['storage_key']).parts
                or str(UUID(objects['currentVersion']))!=objects['currentVersion']):
            raise ValueError('native_disposition_storage_identity')
        prefix='stub/stub/company-documents/'+row['storage_key']+'/'
        if not any(f=={'path':prefix+objects['currentVersion'],'bytes':row['byte_length'],
                      'sha256':command.content_sha256} for f in files):
            raise ValueError('native_disposition_current_bytes_changed')
        if (not files or any(not f['path'].startswith(prefix) or '..' in PurePosixPath(f['path']).parts
                              or f['bytes']<1 or not re.fullmatch('[a-f0-9]{64}',f['sha256']) for f in files)
                or len({f['path'] for f in files})!=len(files)):
            raise ValueError('native_disposition_object_manifest')
        return value,row,objects

    def _observe(self,command):
        value,row,objects=self._state(command)
        key=str(command.document_id);receipt=value['receipts'].get(key)
        # Full company object census; unapproved extra objects cannot be ignored.
        inventory=self.target.objects(action='inventory',keys=[item['storageKey'] for item in value['objects'].values()])
        allfiles=inventory['files']
        company_prefix='stub/stub/company-documents/'+str(command.company_id)+'/'
        actual={f['path']:f for f in allfiles if f['path'].startswith(company_prefix)}
        approved={f['path']:f for item in value['objects'].values() for f in item['files']}
        if any(path not in approved or approved[path]!=f for path,f in actual.items()):
            raise ValueError('native_disposition_unattributed_generation')
        for document,item in value['objects'].items():
            state=value['receipts'].get(document,{}).get('state')
            expected={f['path']:f for f in item['files']}
            present={p:f for p,f in actual.items() if p in expected}
            exists=_storage_presence(inventory['objects'][item['storageKey']],item['currentVersion'])
            # A prepared peer is not permission to ignore its missing history.
            # Only absent Storage metadata can justify its known retirement
            # prefix; otherwise ALL approved generations must still be intact.
            if (state is None and (not exists or present!=expected)
                    or state=='prepared' and exists and present!=expected
                    or state in {'storage_retired','erased'} and (exists or present)):
                raise ValueError('native_disposition_other_object_changed')
        exists=_storage_presence(inventory['objects'][row['storage_key']],objects['currentVersion'])
        present=[f for f in objects['files'] if f['path'] in actual]
        if exists:
            if receipt is None and len(present)==len(objects['files']):return 'NOT_APPLIED'
            if receipt and receipt['state']=='prepared' and len(present)==len(objects['files']):return 'READY'
        elif receipt:
            if receipt['state']=='erased' and not present:return 'ERASED'
            if receipt['state'] in {'prepared','storage_retired'}:return 'RESUMABLE'
        return 'UNKNOWN'

    async def reconcile(self,command):
        return await asyncio.to_thread(self._observe,command)

    async def retained_matches(self,command):
        return command.action=='retain' and await self.reconcile(command)=='NOT_APPLIED'

    def _fence(self,commands):
        if not commands:raise ValueError('native_disposition_empty_inventory')
        if len(commands)>256:raise ValueError('native_disposition_inventory_bound')
        value,_,_=self._state(commands[0])
        if (len(commands)!=len(value['snapshot']) or len({c.document_id for c in commands})!=len(commands)
                or {str(c.document_id) for c in commands}!=set(value['snapshot'])
                or {str(c.document_id) for c in commands if c.action=='erase'}!=set(value['fixtureRecords'])
                or any(c.operation_id!=commands[0].operation_id or c.plan_sha256!=commands[0].plan_sha256 for c in commands)):
            raise ValueError('native_disposition_incomplete_inventory')
        for c in commands:
            self._state(c)

    async def fence_inventory(self,commands):
        await asyncio.to_thread(self._fence,commands)

    async def fence_replay_history(self,commands):
        # This local adapter supports one explicit captured cut per company.
        await self.fence_inventory(commands)

    async def prepare(self,command):
        if command.action!='erase':raise ValueError('native_disposition_erase_required')
        await asyncio.to_thread(self._prepare,command)

    def _prepare(self,command):
        if self._observe(command) not in {'NOT_APPLIED','READY'}:
            raise ValueError('native_disposition_outcome_unknown')
        self._call('prepare',command)

    async def erase(self,command):
        if command.action!='erase':raise ValueError('native_disposition_erase_required')
        await asyncio.to_thread(self._erase,command)

    def _erase(self,command):
        outcome=self._observe(command)
        if outcome=='ERASED':return
        if outcome not in {'READY','RESUMABLE'}:raise ValueError('native_disposition_outcome_unknown')
        value,row,objects=self._state(command)
        if str(command.document_id) not in value['fixtureRecords']:raise ValueError('native_disposition_allowlist')
        if outcome=='READY':
            from urllib.parse import quote
            response=self.target.objects(action='http',method='DELETE',path='/object/company-documents',body={'prefixes':[row['storage_key']]})
            if response['status']!=200:raise ValueError('native_storage_retirement_unresolved')
        # A dropped API response is reconciled against real metadata and the exact
        # approved remaining file subset. SQL metadata remains fenced until done.
        if self._observe(command)!='RESUMABLE':raise ValueError('native_storage_retirement_unresolved')
        self.target.objects(action='gc',prefix='stub/stub/company-documents/'+row['storage_key']+'/',files=objects['files'])
        self._call('storage_retired',command)
        self._call('finalize',command)
