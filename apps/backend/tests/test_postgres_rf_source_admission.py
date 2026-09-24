"""Guarded RF scope keeps every owner call on the opened authenticated connection."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from talli_backend.adapters.postgres_shareholder_register_filing import _source_admission_company
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CorrelationId
from test_consequential_adapter_guards import rf_session
from test_rf1086_source_admission import AdmissionHarness, COMPANY, YEAR


def projection(h):
    company=h.source.command.case.company
    return {'companyId':str(COMPANY),'incomeYear':int(YEAR),'organizationNumber':company.org_number,
        'legalName':company.name,'entityType':'AS','address':company.address,'postalCode':company.postal_code,
        'city':company.city,'identityConfirmedAt':h.identity.identity_confirmed_at,
        'identityLockedAt':h.identity.identity_locked_at,'acceptedOwner':True,'consequentialOperationsAllowed':True}


@pytest.mark.parametrize('change',[('acceptedOwner',False),('consequentialOperationsAllowed',False),
    ('incomeYear',True),('companyId',str(uuid4())),('entityType','ENK'),('identityLockedAt',None),
    ('identityConfirmedAt','2026-01-01T00:00:00'),('legalName','')],
    ids=['owner','eligibility','year','company','entity','unconfirmed','naive-time','missing-name'])
def test_malformed_company_owner_projection_never_becomes_trusted_context(change):
    h=AdmissionHarness(); value=projection(h); value[change[0]]=change[1]
    with pytest.raises(rf.ShareholderRegisterFilingError):
        _source_admission_company(value,rf.Rf1086SourceQuery(COMPANY,YEAR,h.actor))


def test_projection_matches_capture_timestamp_precision():
    h=AdmissionHarness(); value=projection(h)
    value['identityConfirmedAt']='2026-01-01T00:00:00.123+00:00'
    identity=_source_admission_company(value,rf.Rf1086SourceQuery(COMPANY,YEAR,h.actor))
    assert identity.identity_confirmed_at=='2026-01-01T00:00:00.123000+00:00'


def test_actual_scope_orders_company_before_year_and_reuses_connection_then_expires():
    h=AdmissionHarness(); store=rf_session(); calls=[]
    query=rf.Rf1086SourceQuery(COMPANY,YEAR,store.actor_id)
    class Connection:
        info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        async def execute(self,sql,args=()): calls.append((sql,args)); return self
        async def fetchone(self): return {'admission':projection(h)}
    db=Connection()
    @asynccontextmanager
    async def transaction(): yield db
    store._transaction=transaction
    async def current(connection,company,year):
        assert connection is db and company==COMPANY and year==YEAR; return h.source
    async def preview(connection,preview_id):
        assert connection is db and preview_id==h.preview.preview_id; return h.preview
    async def register(connection,actual_query,observation_id,*,current=False):
        assert connection is db and actual_query==query and current; return None
    store._current_year_source=current;store._read_source_preview=preview;store._read_register_observation=register
    async def run():
        async with store.source_admission(query) as scoped:
            assert calls[0][0].startswith('select public.company_access_read_rf_admission_v1(')
            assert calls[1][0].startswith('select shareholder_register_filing.lock_year_source_v1(')
            assert await scoped.current_source()==h.source
            assert await scoped.source_preview(h.preview.preview_id)==h.preview
            assert await scoped.read_current_register_observation(query,rf.Rf1086RegisterObservationId(str(uuid4()))) is None
            with pytest.raises(rf.ShareholderRegisterFilingError):
                await scoped.read_current_register_observation(replace(query,income_year=type(YEAR)(2023)),rf.Rf1086RegisterObservationId(str(uuid4())))
        for action in (scoped.company_identity,scoped.current_source):
            with pytest.raises(rf.ShareholderRegisterFilingError): await action()
    asyncio.run(run())


def test_bridge_uses_guarded_connection_and_rejects_changed_projection_and_expired_scope():
    import hashlib
    from talli_backend.adapters.postgres_shareholder_register_filing import _SourceAdmission
    h=AdmissionHarness();store=rf_session();calls=[]
    query=rf.Rf1086SourceQuery(COMPANY,YEAR,store.actor_id)
    class Connection:
        info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        async def execute(self,sql,args):calls.append((sql,args));return self
        async def fetchone(self):return {'id':h.preview.preview_id.value}
    db=Connection()
    async def read(connection,preview_id):
        assert connection is db;return h.preview
    store._read_source_preview=read
    scope=_SourceAdmission(store,db,query,h.identity)
    async def run():
        assert await scope.bridge_source_preview(h.preview)==h.preview.preview_id
        assert calls==[('select shareholder_register_filing.bridge_source_preview_v1(%s::uuid,%s,%s) as id',
            (h.preview.preview_id.value,hashlib.sha256(rf.serialize_rf1086_source_preview(h.preview).encode()).hexdigest(),str(store.actor_id.subject)))]
        with pytest.raises(rf.Rf1086YearSourceError):
            await scope.bridge_source_preview(replace(h.preview,preview_text='changed review'))
        with pytest.raises(rf.Rf1086YearSourceError):
            await scope.bridge_source_preview(replace(h.preview,income_year=type(YEAR)(2023)))
        scope.close()
        with pytest.raises(rf.ShareholderRegisterFilingError):await scope.bridge_source_preview(h.preview)
        assert len(calls)==1
    asyncio.run(run())


def approval_context(h,entitlement):
    return {'companyId':str(COMPANY),'incomeYear':int(YEAR),'previewId':h.preview.preview_id.value,
        'sourceId':h.source.source_id.value,'sourceSha256':h.source.source_sha256,
        'entitlementId':entitlement,'reviewSha256':'a'*64,
        'warningCodes':sorted({i.code for i in h.preview.readiness_issues if i.level=='warning'}),'blockers':[]}


@pytest.mark.parametrize('field,value',[('companyId',str(uuid4())),('incomeYear',True),
    ('previewId',str(uuid4())),('sourceId',str(uuid4())),('sourceSha256','f'*64),
    ('entitlementId',str(uuid4())),('reviewSha256','A'*64),('warningCodes',['x','x']),
    ('blockers',[' ']),('blockers',['z','a']),('internalReview',{})],
    ids=['company','year','preview','source','source-hash','entitlement','review-hash','duplicate-warning','blank-blocker','unordered-blockers','extra-field'])
def test_approval_context_rejects_incoherent_owner_projection(field,value):
    from talli_backend.adapters.postgres_shareholder_register_filing import _source_approval_review
    h=AdmissionHarness();entitlement=str(uuid4());wire=approval_context(h,entitlement);wire[field]=value
    with pytest.raises(rf.Rf1086ProductionError):
        _source_approval_review(wire,rf.Rf1086SourceQuery(COMPANY,YEAR,h.actor),h.preview,entitlement)


def test_approval_context_and_append_use_one_live_connection_and_exact_manifest_bytes():
    from talli_backend.adapters.postgres_shareholder_register_filing import _SourceAdmission
    h=AdmissionHarness();store=rf_session();entitlement=str(uuid4());approval_id=str(uuid4());calls=[]
    query=rf.Rf1086SourceQuery(COMPANY,YEAR,store.actor_id);wire=approval_context(h,entitlement)
    class Connection:
        info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        async def execute(self,sql,args):calls.append((sql,args));return self
        async def fetchone(self):
            if 'read_source_approval_context' in calls[-1][0]:return {'context':wire}
            return {'id':approval_id,'company_id':str(COMPANY),'income_year':int(YEAR)}
    db=Connection()
    async def read(connection,preview_id):
        assert connection is db and preview_id==h.preview.preview_id;return h.preview
    store._read_source_preview=read;scope=_SourceAdmission(store,db,query,h.identity)
    async def run():
        review=await scope.read_source_approval_context(h.preview.preview_id,entitlement)
        assert review.can_approve and review.source_id==h.source.source_id
        manifest=rf.build_rf1086_source_approval_manifest(rf.Rf1086SourceApprovalManifestBasis(
            h.source,h.preview,store.actor_id,entitlement,review.review_sha256,review.warning_codes))
        result=await scope.append_source_approval(h.preview,entitlement,manifest,review.review_sha256)
        assert result.record_id==approval_id and result.company_id==COMPANY and result.income_year==YEAR
        assert calls[-1][1]==(h.preview.preview_id.value,entitlement,
            rf.serialize_rf1086_source_approval_manifest(manifest),manifest.manifest_sha256,'a'*64,str(store.actor_id.subject))
        with pytest.raises(rf.Rf1086ProductionError):
            await scope.append_source_approval(h.preview,str(uuid4()),manifest,'a'*64)
        assert len(calls)==2
        async def rejected(sql,args):
            from psycopg.errors import RaiseException
            raise RaiseException('rf1086_source_predecessor_mismatch')
        db.execute=rejected
        with pytest.raises(rf.Rf1086ProductionError,match='payload_changed'):
            await scope.append_source_approval(h.preview,entitlement,manifest,'a'*64)
        scope.close()
        with pytest.raises(rf.ShareholderRegisterFilingError):await scope.read_source_approval_context(h.preview.preview_id,entitlement)
        with pytest.raises(rf.ShareholderRegisterFilingError):await scope.append_source_approval(h.preview,entitlement,manifest,'a'*64)
    asyncio.run(run())
