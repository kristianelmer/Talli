"""Bind an already admitted synthetic Documents obligation to a fresh native restore.

Recovery retains the original authorization bytes and time. It does not create a
new owner approval or require the old session to become fresh again. The external
journal, independently held minimum, exact backup and byte export are required.
No environment factory, HTTP route, hosted target or company-wide authority.
"""
import json
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from psycopg import sql

from talli_backend.adapters.native_disposition_preflight import NativeDispositionPreflight, _bytes, _sha, _EXPORT
from talli_backend.adapters.postgres_document_disposition import native_document_generation
from talli_backend.adapters.native_restore_binding import verify_native_restore
from talli_backend.modules.company_access.public import AuthorizedLocalDocumentsDisposition


def _read_native_backup(directory):
    directory=Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('native_recovery_backup_unavailable')
    files=sorted(directory.iterdir())
    required={'database.dump','roles.sql','storage_vectors.dump','objects.tar',
              'object-manifest.json','object-attributes.json','bindings.private.json'}
    if not 7<=len(files)<=32 or not required<={p.name for p in files}:
        raise ValueError('native_recovery_backup_unavailable')
    if sum(p.stat().st_size for p in files)>256*1024*1024:
        raise ValueError('native_recovery_backup_unavailable')
    pins={};metadata={}
    for path in files:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>2*1024**3:
            raise ValueError('native_recovery_backup_unavailable')
        digest=sha256();size=0;parts=[]
        with path.open('rb') as source:
            for chunk in iter(lambda:source.read(1024*1024),b''):
                digest.update(chunk);size+=len(chunk)
                if path.name in {'bindings.private.json','object-manifest.json','object-attributes.json'}:
                    if size>32*1024*1024:raise ValueError('native_recovery_backup_unavailable')
                    parts.append(chunk)
        pins[path.name]={'bytes':size,'sha256':digest.hexdigest()}
        if parts:metadata[path.name]=b''.join(parts)
    return _sha(pins),metadata


def native_backup_commitment(directory):
    """Commit the finite native input bundle; the expected digest is held separately."""
    return _read_native_backup(directory)[0]


class NativeDispositionRecovery:
    def __init__(self, *, target, directory):
        self.target=target; self.directory=Path(directory)
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise ValueError('native_recovery_evidence_directory')
        target.validate()

    def _query(self, statement, *values):
        self.target.validate()
        raw=self.target._query(sql.SQL(statement).format(*map(sql.Literal,values)).as_string())
        if len(raw)>32*1024*1024:raise ValueError('native_recovery_fact_bound')
        return json.loads(raw)

    def bind(self, *, journal, minimum, permit, backup_directory, backup_sha256, documents_export):
        if (not isinstance(permit,AuthorizedLocalDocumentsDisposition)
                or str(permit.facts.target_id)==self.target.target or minimum.sequence<1):
            raise ValueError('native_recovery_authorization')
        head,entries=journal.read(minimum=minimum)
        if len(entries)!=1 or head!=minimum:
            raise ValueError('native_recovery_history_unavailable')
        admitted=[p for p in entries if p.plan.operation_id==permit.plan.operation_id]
        if (len(admitted)!=1 or admitted[0].model_dump_json()!=permit.model_dump_json()
                or next(i for i,p in enumerate(entries,1) if p.plan.operation_id==permit.plan.operation_id)>minimum.sequence):
            raise ValueError('native_recovery_authorization')
        observed_backup,backup_metadata=_read_native_backup(backup_directory)
        if observed_backup!=backup_sha256:
            raise ValueError('native_recovery_backup_changed')
        path=Path(documents_export)
        if path.is_symlink() or not path.is_file() or path.stat().st_size>32*1024*1024:
            raise ValueError('native_recovery_export_unavailable')
        raw=path.read_bytes()
        if sha256(raw).hexdigest()!=permit.facts.documents_export_sha256:
            raise ValueError('native_recovery_export_changed')
        archive=json.loads(raw); plan=permit.plan; company=plan.company_id
        if (set(archive)!={'scope','companyId','generation','documents','references','originals','files'}
                or archive['scope']!=permit.facts.scope or archive['companyId']!=str(company)
                or archive['generation']!=plan.generation):
            raise ValueError('native_recovery_export_changed')
        with self.target.source_fence(company):
            native_profile=verify_native_restore(self.target,backup_metadata)
            source=self._query("""select jsonb_build_object(
              'documents',(select coalesce(jsonb_object_agg(d.id::text,to_jsonb(d)),'{{}}') from public.documents d where company_id={0}),
              'references',(select coalesce(jsonb_agg(to_jsonb(e) order by e.document_id,e.source_capability,e.source_record_id),'[]') from documents.evidence_references e where company_id={0}),
              'originals',(select coalesce(jsonb_agg(to_jsonb(o) order by o.document_id),'[]') from documents.retained_originals o where company_id={0}),
              'generations',(select coalesce(jsonb_agg(jsonb_build_array(income_year,generation) order by income_year),'[]') from public.company_archive_source_generations where company_id={0}),
              'sourceTarget',(select to_jsonb(t) from documents.local_native_disposition_targets t where target_id={1}))""",company,permit.facts.target_id)
            rows=source['documents']
            if (not 1<=len(rows)<=256 or any(source[k]!=archive[k] for k in ('documents','references','originals'))
                    or source['generations']!=[list(v) for v in permit.facts.source_generations]):
                raise ValueError('native_recovery_snapshot_changed')
            prior=source['sourceTarget']
            if not prior or prior['system_identifier']==self.target.system or prior['operator_login']!=self.target.login:
                raise ValueError('native_recovery_source_binding')
            inventory=self.target.objects(action='inventory',keys=[r['storage_key'] for r in rows.values()])
            files=[f for f in inventory['files'] if f['path'].startswith('stub/stub/company-documents/'+str(company)+'/')]
            exported=json.loads(self.target._run('exec','-i',self.target.storage,'node','-e',_EXPORT,data=_bytes({'files':files})))
            if sorted(exported,key=lambda f:f['path'])!=sorted(archive['files'],key=lambda f:f['path']):
                raise ValueError('native_recovery_storage_changed')
            objects={}
            for key,row in sorted(rows.items()):
                response=inventory['objects'][row['storage_key']]
                if response['status']!=200:raise ValueError('native_recovery_storage_changed')
                version=json.loads(response['body'])['version']; UUID(version)
                prefix='stub/stub/company-documents/'+row['storage_key']+'/'
                versions=[f for f in files if f['path'].startswith(prefix)]
                objects[key]={'storageKey':row['storage_key'],'currentVersion':version,'files':versions}
            if (_sha({'generations':tuple(tuple(v) for v in source['generations']),'snapshot':rows,'objects':objects})!=plan.generation
                    or {str(r.record_id) for r in plan.records}!=set(rows)
                    or any(native_document_generation(rows[str(r.record_id)],objects[str(r.record_id)]['files'])!=r.generation for r in plan.records)):
                raise ValueError('native_recovery_generation_changed')
            body=permit.model_dump_json(); commitment=sha256(body.encode()).hexdigest()
            binding={'version':1,'sourceTarget':str(permit.facts.target_id),'target':self.target.target,
                'sourceSystemIdentifier':prior['system_identifier'],'sourceSnapshotSha256':prior['source_snapshot_sha256'],
                'systemIdentifier':self.target.system,'operatorLogin':self.target.login,'backupSha256':backup_sha256,
                'nativeProfile':native_profile,
                'authorizationSha256':commitment,'exportSha256':permit.facts.documents_export_sha256,
                'journal':{'stream':head.stream,'sequence':head.sequence,'sha256':head.sha256},
                'operationId':str(plan.operation_id),'companyGeneration':plan.generation}
            binding_sha=_sha(binding)
            values=(plan.operation_id,company,commitment,self.target.login,permit.owner_subject,plan.generation,
                json.dumps(rows),json.dumps(objects),[r.record_id for r in plan.records if r.action=='erase'],body,
                self.target.target,self.target.system,binding_sha)
            # Both registrations preserve the exact original authorization. A
            # collision rolls back the whole transaction instead of rebinding it.
            observed=self._query("""begin;
              insert into documents.local_native_disposition_plans(operation_id,company_id,plan_sha256,operator_login,
                approved_owner,company_generation,metadata_snapshot,object_manifest,fixture_records,authorization_evidence)
                values({0},{1},{2},{3},{4},{5},{6}::jsonb,{7}::jsonb,{8}::uuid[],{9}::jsonb) on conflict do nothing;
              insert into documents.local_native_disposition_targets values({10},{11},{3},{12}) on conflict do nothing;
              do $binding$ begin
                if not exists(select 1 from documents.local_native_disposition_plans where operation_id={0}
                  and company_id={1} and plan_sha256={2} and operator_login={3} and approved_owner={4}
                  and company_generation={5} and metadata_snapshot={6}::jsonb and object_manifest={7}::jsonb
                  and fixture_records={8}::uuid[] and authorization_evidence={9}::jsonb)
                  or not exists(select 1 from documents.local_native_disposition_targets where target_id={10}
                    and system_identifier={11} and operator_login={3} and source_snapshot_sha256={12})
                then raise exception 'native_recovery_registration_changed'; end if;
              end $binding$;
              select jsonb_build_object('authorization',authorization_evidence,'binding',{12})
                from documents.local_native_disposition_plans where operation_id={0}; commit;""",*values)
            if observed!={'authorization':json.loads(body),'binding':binding_sha}:
                raise ValueError('native_recovery_registration_changed')
            NativeDispositionPreflight._write_once(self.directory/(str(plan.operation_id)+'.recovery.json'),_bytes(binding))
            return binding
