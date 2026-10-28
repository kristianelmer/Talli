"""Owning-fact verification on explicitly owned disposable native targets only.

No environment factory, HTTP route, hosted DSN, or production registration. The
local controller channel reads Auth/Company Access/Documents observations; Billing
is drained through its ordinary verified-owner public port. Missing whole-company
owners and legal-export coverage are reported, never asserted complete.
"""
import base64
from dataclasses import asdict
from datetime import datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import UUID

from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from talli_backend.adapters.postgres_document_disposition import native_document_generation
from talli_backend.adapters.supabase_annual_billing import SupabaseAnnualBillingAdapter
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration
from talli_backend.modules.billing.public import AnnualPurchaseHistoryQuery, AnnualPurchasePage, disposition_access_period
from talli_backend.modules.company_access.public import (
    CompanyDispositionPlan, DispositionRecord, DispositionSession, LocalDocumentsFacts,
    authorize_local_documents_disposition,
)
from talli_backend.modules.documents.public import DocumentDisposition
from talli_backend.shared.kernel import CompanyId


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()


def _sha(value):
    return sha256(_bytes(value)).hexdigest()


def _instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


_AUTH = r"""
const fs=require('fs');const x=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{const r=await fetch('http://'+x.host+':9999/user',{headers:{Authorization:'Bearer '+x.token},redirect:'error',signal:AbortSignal.timeout(5000)});
const body=await r.text();if(r.status!==200||body.length>65536)throw Error();const u=JSON.parse(body);
if(typeof u.id!=='string')throw Error();process.stdout.write(JSON.stringify({id:u.id}));})().catch(()=>process.exit(1));
"""

_EXPORT = r"""
const fs=require('fs'),path=require('path'),crypto=require('crypto');const x=JSON.parse(fs.readFileSync(0,'utf8'));
let total=0;const files=x.files.map(f=>{const p=path.join('/mnt',f.path);const s=fs.lstatSync(p);if(!s.isFile()||s.isSymbolicLink()||f.path.split('/').includes('..'))throw Error();
const b=fs.readFileSync(p);total+=b.length;if(total>16777216||b.length!==f.bytes||crypto.createHash('sha256').update(b).digest('hex')!==f.sha256)throw Error();return {...f,base64:b.toString('base64')};});process.stdout.write(JSON.stringify(files));
"""


class NativeDispositionPreflight:
    def __init__(self, *, target, auth_container, auth_image, gateway, billing_database_url, directory):
        self.target=target; self.auth=auth_container; self.auth_image=auth_image; self.gateway=gateway
        self.directory=Path(directory).absolute()
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise ValueError('local_disposition_evidence_directory')
        origin=self._validate_services()
        connection=conninfo_to_dict(billing_database_url); native=conninfo_to_dict(target.database_url)
        if (any(connection.get(k)!=native.get(k) for k in ('host','port','dbname'))
                or any(k in connection for k in ('hostaddr','service','passfile','options'))):
            raise ValueError('local_disposition_billing_target')
        # The public anon key is not required by the direct owned Auth gateway.
        self.billing=SupabaseAnnualBillingAdapter(LedgerSupabaseConfiguration(
            url=origin, anon_key='local-controller-public-placeholder', database_url=billing_database_url))

    def _validate_services(self):
        self.target.validate()
        auth=json.loads(self.target._run('inspect',self.auth))[0]
        gateway=json.loads(self.target._run('inspect',self.gateway))[0]
        for resource in (auth,gateway):
            if resource['Config'].get('Labels',{}).get(self.target.label)!=self.target.nonce:
                raise ValueError('local_disposition_service_binding')
        if (auth['Image']!=self.auth_image or set(auth['NetworkSettings']['Networks'])!={self.target.network}
                or any(auth['NetworkSettings']['Ports'].values())
                or self.target.network not in gateway['NetworkSettings']['Networks']):
            raise ValueError('local_disposition_auth_binding')
        bindings=gateway['NetworkSettings']['Ports'].get('19997/tcp',[])
        if len(bindings)!=1 or bindings[0]['HostIp']!='127.0.0.1':
            raise ValueError('local_disposition_gateway_binding')
        self.auth_host=auth['Name'].lstrip('/')
        return 'http://127.0.0.1:'+bindings[0]['HostPort']

    def _session(self, token):
        self._validate_services()
        if not isinstance(token,str) or len(token)>16384:
            raise ValueError('local_disposition_session')
        # Auth checks signature/expiry before any JWT selector is decoded.
        try:
            user=json.loads(self.target._run('exec','-i',self.target.storage,'node','-e',_AUTH,
                data=_bytes({'host':self.auth_host,'token':token})))
            claims=json.loads(base64.urlsafe_b64decode(token.split('.')[1]+'==='))
            subject=UUID(user['id']); session=UUID(claims['session_id'])
            if claims['sub']!=str(subject) or claims.get('aal')!='aal2':
                raise ValueError()
        except Exception:
            raise ValueError('local_disposition_session') from None
        return subject,session

    def _query(self, statement, *values):
        self.target.validate()
        raw=self.target._query(sql.SQL(statement).format(*map(sql.Literal,values)).as_string())
        if len(raw)>32*1024*1024:
            raise ValueError('local_disposition_fact_bound')
        return json.loads(raw)

    def _source(self, company, case, owner, reviewer):
        # Local control-plane observation, no Auth secrets or provider payloads.
        counts=self._query("""select jsonb_build_object(
          'documents',(select count(*) from public.documents where company_id={0}),
          'references',(select count(*) from documents.evidence_references where company_id={0}),
          'originalBytes',(select coalesce(sum(octet_length(content)),0) from documents.retained_originals where company_id={0}))""",company)
        if counts['documents']>256 or counts['references']>2048 or counts['originalBytes']>16*1024*1024:
            raise ValueError('local_disposition_fact_bound')
        return self._query("""select jsonb_build_object(
          'now',clock_timestamp(),
          'owner', (select jsonb_build_object('subject',s.user_id,'session',s.id,'aal',s.aal,'notAfter',s.not_after,
             'mfaAt',(select max(m.updated_at) from auth.mfa_amr_claims m where m.session_id=s.id and m.authentication_method='totp'))
             from auth.sessions s where s.user_id={0} and s.id={1}),
          'reviewer', (select jsonb_build_object('subject',s.user_id,'session',s.id,'aal',s.aal,'notAfter',s.not_after,
             'mfaAt',(select max(m.updated_at) from auth.mfa_amr_claims m where m.session_id=s.id and m.authentication_method='totp'))
             from auth.sessions s where s.user_id={2} and s.id={3}),
          'membership',(select to_jsonb(m) from public.company_memberships m where m.company_id={4} and m.user_id={0}),
          'operator',(select to_jsonb(o) from public.support_operators o where o.user_id={2}),
          'grant',(select to_jsonb(g) from public.support_access_grants g where g.case_id={5} and g.company_id={4} and g.operator_user_id={2}),
          'opening',(select to_jsonb(o) from public.support_case_openings o where o.case_id={5} and o.company_id={4} and o.actor_id={2} limit 1),
          'generations',(select coalesce(jsonb_agg(jsonb_build_array(income_year,generation) order by income_year),'[]') from public.company_archive_source_generations where company_id={4}),
          'companyExports',(select coalesce(jsonb_agg(to_jsonb(r) order by r.id),'[]') from public.company_archive_export_receipts r where r.company_id={4}),
          'documents',(select coalesce(jsonb_object_agg(d.id::text,to_jsonb(d)),'{{}}') from public.documents d where d.company_id={4}),
          'references',(select coalesce(jsonb_agg(to_jsonb(e) order by e.document_id,e.source_capability,e.source_record_id),'[]') from documents.evidence_references e where e.company_id={4}),
          'originals',(select coalesce(jsonb_agg(to_jsonb(o) order by o.document_id),'[]') from documents.retained_originals o where o.company_id={4})
        )""",*owner,*reviewer,company,case)

    @staticmethod
    def _authority(source, company, case):
        now=_instant(source['now']); sessions=[]
        for name,role in (('owner','owner'),('reviewer','reviewer')):
            value=source[name]
            if (not value or value['aal']!='aal2' or not value['mfaAt']
                    or not timedelta(0)<=now-_instant(value['mfaAt'])<=timedelta(minutes=5)
                    or (value['notAfter'] and _instant(value['notAfter'])<=now)):
                raise ValueError('local_disposition_fresh_session')
            sessions.append(DispositionSession(subject=UUID(value['subject']),session_id=UUID(value['session']),
                role=role,company_id=company,mfa_at=_instant(value['mfaAt'])))
        if sessions[0].subject==sessions[1].subject or sessions[0].session_id==sessions[1].session_id:
            raise ValueError('local_disposition_independent_review')
        member=source['membership']; operator=source['operator']; grant=source['grant']
        if not member or member['role']!='owner' or not member['accepted_at']:
            raise ValueError('local_disposition_owner')
        if not operator or not operator['active'] or operator['role']!='admin':
            raise ValueError('local_disposition_reviewer')
        if (not grant or not source['opening'] or grant['revoked_at'] is not None
                or grant['granted_by']!=str(sessions[1].subject)
                or not _instant(grant['starts_at'])<=now<_instant(grant['expires_at'])
                or not {'documents','billing','cancellation'}<=set(grant['scopes'])):
            raise ValueError('local_disposition_support_authority')
        return now,*sessions

    async def observe(self, *, operation_id, company_id, support_case_id, erase_ids, owner_token, reviewer_token):
        """Selectors only; approval, dates, inventories and completeness are not inputs."""
        operation_id=UUID(str(operation_id)); company=UUID(str(company_id)); case=UUID(str(support_case_id))
        erase_ids=tuple(UUID(str(v)) for v in erase_ids)
        if not 1<=len(erase_ids)<=16 or len(set(erase_ids))!=len(erase_ids):
            raise ValueError('local_disposition_selection')
        owner=self._session(owner_token); reviewer=self._session(reviewer_token)
        source=self._source(company,case,owner,reviewer)
        now,owner_session,reviewer_session=self._authority(source,company,case)
        rows=source['documents']
        if not 1<=len(rows)<=256 or not set(map(str,erase_ids))<=set(rows):
            raise ValueError('local_disposition_inventory_unavailable')
        session=await self.billing.session(owner_token)
        purchases=[]; cursor=None; seen=set()
        for _ in range(20):
            page=await session.reads.read_purchase_history(AnnualPurchaseHistoryQuery(
                company_id=CompanyId(str(company)),actor_id=session.actor_id,before_purchase_id=cursor))
            for purchase in page.purchases:
                if str(purchase.purchase_id) in seen:
                    raise ValueError('local_disposition_billing_history_incomplete')
                seen.add(str(purchase.purchase_id)); purchases.append(purchase)
            if page.next_purchase_id is None:break
            if not page.purchases or page.next_purchase_id==cursor:
                raise ValueError('local_disposition_billing_history_incomplete')
            cursor=page.next_purchase_id
        else:raise ValueError('local_disposition_billing_history_incomplete')
        generations=tuple(tuple(g) for g in source['generations'])
        years=tuple(sorted({r['income_year'] for r in rows.values()}))
        all_years=tuple(sorted({y for y,_ in generations}|set(years)|{int(p.income_year) for p in purchases}))
        period=disposition_access_period(AnnualPurchasePage(tuple(purchases),None),company_id=company,all_company_years=all_years)
        export_until=max(period.read_export_until,period.paid_expires_at+timedelta(days=90))
        if now<export_until:raise ValueError('local_disposition_export_period_active')
        inventory=self.target.objects(action='inventory',keys=[r['storage_key'] for r in rows.values()])
        objects={}; records=[]; files=inventory['files']; linked={r['document_id'] for r in source['references']+source['originals']}
        for key,row in sorted(rows.items()):
            response=inventory['objects'][row['storage_key']]
            if response['status']!=200:raise ValueError('local_disposition_storage_unavailable')
            version=json.loads(response['body'])['version']; UUID(version)
            prefix='stub/stub/company-documents/'+row['storage_key']+'/'
            versions=[f for f in files if f['path'].startswith(prefix)]
            if {'path':prefix+version,'bytes':row['byte_length'],'sha256':row['content_sha256']} not in versions:
                raise ValueError('local_disposition_storage_unavailable')
            created=_instant(row['created_at']); retention_years=row['retention_years']
            if type(retention_years) is not int or retention_years<0:
                raise ValueError('local_disposition_legal_source_unavailable')
            try:until=created.replace(year=created.year+retention_years)
            except ValueError:until=created.replace(year=created.year+retention_years,month=3,day=1)
            erase=UUID(key) in erase_ids
            if erase and (key in linked or until>now):raise ValueError('local_disposition_retention')
            if not erase and until<=now:raise ValueError('local_disposition_legal_source_unavailable')
            objects[key]={'storageKey':row['storage_key'],'currentVersion':version,'files':versions}
            records.append(DispositionRecord(owner='documents',record_id=UUID(key),income_year=row['income_year'],
                generation=native_document_generation(row,versions),content_sha256=row['content_sha256'],
                action='erase' if erase else 'retain',retention_until=until))
        expected={f['path'] for o in objects.values() for f in o['files']}
        actual={f['path'] for f in files if f['path'].startswith('stub/stub/company-documents/'+str(company)+'/')}
        # Unknown company object keys/versions cannot disappear from the export.
        if actual!=expected:raise ValueError('local_disposition_inventory_unavailable')
        stable={k:v for k,v in source.items() if k!='now'}
        stable['billing']=[asdict(p) for p in purchases]; stable['objects']=objects
        source_sha=_sha(stable)
        plan=CompanyDispositionPlan(operation_id=operation_id,company_id=company,choice='delete',years=years,
            generation=_sha({'generations':generations,'snapshot':rows,'objects':objects}),records=tuple(records),
            inventory_sha256='0'*64,support_case_id=case)
        plan=plan.model_copy(update={'inventory_sha256':plan.inventory_digest()})
        exported=json.loads(self.target._run('exec','-i',self.target.storage,'node','-e',_EXPORT,
            data=_bytes({'files':[f for o in objects.values() for f in o['files']]})))
        archive=_bytes({'scope':'local-documents-only','companyId':str(company),'generation':plan.generation,
            'documents':rows,'references':source['references'],'originals':source['originals'],'files':exported})
        digest=sha256(archive).hexdigest(); path=self.directory/(digest+'.documents-export.json')
        self._write_once(path,archive)
        return {'plan':plan,'source':stable,'source_sha256':source_sha,'objects':objects,'rows':rows,
            'now':now,'owner':owner_session,'reviewer':reviewer_session,'paid_expires_at':period.paid_expires_at,
            'recorded_export_until':period.read_export_until,'export_until':export_until,
            'export_sha256':digest,'generations':generations,
            'whole_company':{'available':False,'reason':'owning_inventory_legal_and_export_coverage_unavailable',
                'observedCompanyExportReceipts':len(source['companyExports'])}}

    def _write_once(self,path,body):
        if path.exists():
            if path.is_symlink() or path.read_bytes()!=body:raise ValueError('local_disposition_evidence_changed')
            return
        with path.open('xb') as output:
            os.chmod(path,0o600);output.write(body);output.flush();os.fsync(output.fileno())
        fd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)

    async def approve(self, *, reviewed_plan_sha256, **selectors):
        observed=await self.observe(**selectors)
        plan=observed['plan']; commitment=sha256(plan.model_dump_json().encode()).hexdigest()
        if reviewed_plan_sha256!=commitment:raise ValueError('local_disposition_review_changed')
        facts=LocalDocumentsFacts(source_sha256=observed['source_sha256'],source_generations=observed['generations'],
            paid_expires_at=observed['paid_expires_at'],recorded_export_until=observed['recorded_export_until'],
            export_until=observed['export_until'],documents_export_sha256=observed['export_sha256'],
            owner=observed['owner'],reviewer=observed['reviewer'],review_plan_sha256=commitment,
            support_case_id=plan.support_case_id)
        permit=authorize_local_documents_disposition(plan,facts,now=observed['now'])
        self._write_once(self.directory/(str(plan.operation_id)+'.review.json'),permit.model_dump_json().encode())
        return permit

    async def revalidate(self, permit, **selectors):
        observed=await self.observe(**selectors)
        if (observed['plan']!=permit.plan or observed['source_sha256']!=permit.facts.source_sha256
                or observed['export_sha256']!=permit.facts.documents_export_sha256
                or self.directory.joinpath(str(permit.plan.operation_id)+'.review.json').read_bytes()!=permit.model_dump_json().encode()):
            raise ValueError('local_disposition_source_changed')
        return observed

    async def execute(self, permit, *, journal, store, **selectors):
        """Admit current facts under the company fence, then use the native owner.

        Session revocation before admission refuses the operation. A durable
        admitted tombstone remains a recovery obligation after a later sign-out.
        """
        from talli_backend.application.company_disposition import execute_authorized_disposition
        if store.target is not self.target:
            raise ValueError('local_disposition_execution_target')
        with self.target.source_fence(permit.plan.company_id):
            observed=await self.revalidate(permit,**selectors)
            # Acknowledged journal durability precedes registration/preparation.
            journal.append(permit)
            values=(permit.plan.operation_id,permit.plan.company_id,sha256(permit.model_dump_json().encode()).hexdigest(),
                self.target.login,permit.owner_subject,permit.plan.generation,json.dumps(observed['rows']),
                json.dumps(observed['objects']),[r.record_id for r in permit.plan.records if r.action=='erase'],
                permit.model_dump_json())
            self._query("""with inserted as (
                insert into documents.local_native_disposition_plans(operation_id,company_id,plan_sha256,
                  operator_login,approved_owner,company_generation,metadata_snapshot,object_manifest,fixture_records,authorization_evidence)
                values({0},{1},{2},{3},{4},{5},{6}::jsonb,{7}::jsonb,{8}::uuid[],{9}::jsonb)
                on conflict do nothing returning operation_id)
                select count(*) from inserted""",*values)
            return await execute_authorized_disposition(permit,journal=journal,target=self.target.target,stores={'documents':store})

    @staticmethod
    def commands(permit):
        commitment=sha256(permit.model_dump_json().encode()).hexdigest()
        return tuple(DocumentDisposition(permit.plan.operation_id,permit.plan.company_id,r.record_id,
            r.income_year,r.generation,r.content_sha256,permit.plan.generation,commitment,r.action) for r in permit.plan.records)
