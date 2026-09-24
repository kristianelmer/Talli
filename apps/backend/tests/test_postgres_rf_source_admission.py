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
