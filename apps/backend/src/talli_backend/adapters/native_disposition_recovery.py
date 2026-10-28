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
from talli_backend.adapters.postgres_document_disposition import MAX_NATIVE_CUTS, native_document_generation
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
        archive=self._export(permit,documents_export);plan=permit.plan;company=plan.company_id
        with self.target.source_fence(company):
            native_profile=verify_native_restore(self.target,backup_metadata)
            rows,objects,prior=self._initial_state(permit,archive)
            body=permit.model_dump_json(); commitment=sha256(body.encode()).hexdigest()
            binding={'version':1,'sourceTarget':str(permit.facts.target_id),'target':self.target.target,
                'sourceSystemIdentifier':prior['system_identifier'],'sourceSnapshotSha256':prior['source_snapshot_sha256'],
                'systemIdentifier':self.target.system,'operatorLogin':self.target.login,'backupSha256':backup_sha256,
                'nativeProfile':native_profile,
                'authorizationSha256':commitment,'exportSha256':permit.facts.documents_export_sha256,
                'journal':{'stream':head.stream,'sequence':head.sequence,'sha256':head.sha256},
                'operationId':str(plan.operation_id),'companyGeneration':plan.generation}
            binding_sha=_sha(binding)
            self._register(((permit,rows,objects),),binding_sha)
            NativeDispositionPreflight._write_once(self.directory/(str(plan.operation_id)+'.recovery.json'),_bytes(binding))
            return binding

    @staticmethod
    def _export(permit,path_value):
        path=Path(path_value)
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
        return archive

    def _initial_state(self,permit,archive):
        plan=permit.plan;company=plan.company_id
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
        return rows,objects,prior

    def _register(self,prepared,binding_sha):
        statements=['begin;']
        for permit,rows,objects in prepared:
            plan=permit.plan;body=permit.model_dump_json();commitment=sha256(body.encode()).hexdigest()
            values=(plan.operation_id,plan.company_id,commitment,self.target.login,permit.owner_subject,plan.generation,
                json.dumps(rows),json.dumps(objects),[r.record_id for r in plan.records if r.action=='erase'],body)
            statements.append(sql.SQL("""
              insert into documents.local_native_disposition_plans(operation_id,company_id,plan_sha256,operator_login,
                approved_owner,company_generation,metadata_snapshot,object_manifest,fixture_records,authorization_evidence)
                values({0},{1},{2},{3},{4},{5},{6}::jsonb,{7}::jsonb,{8}::uuid[],{9}::jsonb) on conflict do nothing;
              do $binding$ begin
                if not exists(select 1 from documents.local_native_disposition_plans where operation_id={0}
                  and company_id={1} and plan_sha256={2} and operator_login={3} and approved_owner={4}
                  and company_generation={5} and metadata_snapshot={6}::jsonb and object_manifest={7}::jsonb
                  and fixture_records={8}::uuid[] and authorization_evidence={9}::jsonb)
                then raise exception 'native_recovery_registration_changed'; end if;
              end $binding$;""").format(*map(sql.Literal,values)).as_string())
        statements.append(sql.SQL("""
          insert into documents.local_native_disposition_targets values({0},{1},{2},{3}) on conflict do nothing;
          do $target$ begin
            if not exists(select 1 from documents.local_native_disposition_targets where target_id={0}
              and system_identifier={1} and operator_login={2} and source_snapshot_sha256={3})
            then raise exception 'native_recovery_registration_changed'; end if;
          end $target$;
          select jsonb_build_object('plans',count(*),'binding',{3}) from documents.local_native_disposition_plans
            where operation_id=any({4}::uuid[]); commit;""").format(*map(sql.Literal,
              (self.target.target,self.target.system,self.target.login,binding_sha,[p.plan.operation_id for p,_,_ in prepared]))).as_string())
        self.target.validate();observed=json.loads(self.target._query('\n'.join(statements)))
        if observed!={'plans':len(prepared),'binding':binding_sha}:raise ValueError('native_recovery_registration_changed')

    def bind_prefix(self, *, journal, minimum, permits, backup_directory, backup_sha256, documents_exports):
        """Bind an exact current prefix of deletion-only captured Documents cuts."""
        head,entries=journal.read(minimum=minimum)
        if (head!=minimum or not 1<=len(entries)<=MAX_NATIVE_CUTS or len(permits)!=len(entries)
                or len(documents_exports)!=len(entries)):
            raise ValueError('native_recovery_history_unavailable')
        if any(not isinstance(p,AuthorizedLocalDocumentsDisposition) or p.model_dump_json()!=e.model_dump_json()
               for p,e in zip(permits,entries)):
            raise ValueError('native_recovery_authorization')
        if len(entries)==1:
            return self.bind(journal=journal,minimum=minimum,permit=permits[0],backup_directory=backup_directory,
                backup_sha256=backup_sha256,documents_export=documents_exports[0])
        first=permits[0];company=first.plan.company_id
        if (str(first.facts.target_id)==self.target.target
                or any(p.plan.company_id!=company or p.facts.target_id!=first.facts.target_id
                    or p.owner_subject!=first.owner_subject for p in permits)
                or any(a.authorized_at>b.authorized_at for a,b in zip(permits,permits[1:]))):
            raise ValueError('native_recovery_authorization')
        observed,metadata=_read_native_backup(backup_directory)
        if observed!=backup_sha256:raise ValueError('native_recovery_backup_changed')
        archives=[self._export(p,path) for p,path in zip(permits,documents_exports)]
        with self.target.source_fence(company):
            profile=verify_native_restore(self.target,metadata,require_generation_guard=True)
            rows,base_objects,prior=self._initial_state(first,archives[0])
            generations=dict(first.facts.source_generations);remaining=dict(rows);prepared=[];operations=[]
            remaining_files=archives[0]['files'];seen=set()
            for sequence,(permit,archive) in enumerate(zip(permits,archives),1):
                objects={key:base_objects[key] for key in remaining}
                if (archive['documents']!=remaining or archive['references']!=archives[0]['references']
                        or archive['originals']!=archives[0]['originals']
                        or sorted(archive['files'],key=lambda f:f['path'])!=sorted(remaining_files,key=lambda f:f['path'])
                        or permit.facts.source_generations!=tuple(sorted(generations.items()))
                        or permit.plan.generation!=_sha({'generations':tuple(sorted(generations.items())),'snapshot':remaining,'objects':objects})
                        or {str(r.record_id) for r in permit.plan.records}!=set(remaining)
                        or any(native_document_generation(remaining[str(r.record_id)],objects[str(r.record_id)]['files'])!=r.generation
                            or remaining[str(r.record_id)]['content_sha256']!=r.content_sha256 for r in permit.plan.records)):
                    raise ValueError('native_recovery_history_transition')
                selected={str(r.record_id) for r in permit.plan.records if r.action=='erase'}
                if not selected or selected & seen:raise ValueError('native_recovery_history_transition')
                prepared.append((permit,dict(remaining),objects))
                operations.append({'sequence':sequence,'operationId':str(permit.plan.operation_id),
                    'authorizationSha256':sha256(permit.model_dump_json().encode()).hexdigest(),
                    'authorizedAt':permit.authorized_at.isoformat(),'exportSha256':permit.facts.documents_export_sha256,
                    'companyGeneration':permit.plan.generation,'sourceGenerations':permit.facts.source_generations})
                removed_paths={f['path'] for key in selected for f in objects[key]['files']}
                remaining_files=[f for f in remaining_files if f['path'] not in removed_paths]
                for key in selected:generations[remaining[key]['income_year']]+=1
                remaining={key:row for key,row in remaining.items() if key not in selected};seen.update(selected)
            binding={'version':2,'sourceTarget':str(first.facts.target_id),'target':self.target.target,
                'sourceSystemIdentifier':prior['system_identifier'],'sourceSnapshotSha256':prior['source_snapshot_sha256'],
                'systemIdentifier':self.target.system,'operatorLogin':self.target.login,'backupSha256':backup_sha256,
                'nativeProfile':profile,'journal':{'stream':head.stream,'sequence':head.sequence,'sha256':head.sha256},
                'operations':operations,'historyProfile':'captured-documents-delete-only-v1'}
            # Admission or a changed cut during observation cannot authorize a
            # partly bound target. Publication checks the current head again.
            if journal.read(minimum=minimum)[0]!=head:raise ValueError('native_recovery_history_changed')
            self._register(tuple(prepared),_sha(binding))
            NativeDispositionPreflight._write_once(self.directory/(head.sha256+'.recovery-prefix.json'),_bytes(binding))
            return binding
