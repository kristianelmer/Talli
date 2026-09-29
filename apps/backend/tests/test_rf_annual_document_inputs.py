"""RF reads active document metadata without claiming original-byte integrity."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from talli_backend.adapters.postgres_shareholder_register_filing import _SourceAdmission
from talli_backend.adapters.supabase_documents import SupabaseDocumentMetadataTransaction
from talli_backend.application.shareholder_register_annual_documents import annual_document_inputs
from talli_backend.modules.documents.public import DocumentId, DocumentsError, DocumentStatus
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear
from test_documents import record
from test_postgres_rf_source_admission import rf_session
from test_rf1086_source_admission import AdmissionHarness, COMPANY, YEAR

STORE=rf_session()
QUERY=rf.Rf1086SourceQuery(COMPANY,YEAR,STORE.actor_id)


def document(**changes):
    return replace(record(),document_id=DocumentId(str(uuid4())),company_id=COMPANY,income_year=YEAR,**changes)


def wire(item):
    return dict(id=str(item.document_id),company_id=str(item.company_id),income_year=int(item.income_year),
        document_type=item.document_type,name=item.name,linked_to=item.linked_to,status=item.status.value,
        retention_years=item.retention_years,storage_key=item.storage_key,content_type=item.content_type,
        byte_length=item.byte_length,content_sha256=item.content_sha256,created_by=str(item.created_by.subject),
        created_at=item.created_at,removed_at=item.removed_at,removal_reason=item.removal_reason)


def test_complete_active_metadata_preserves_status_and_linkage_without_selecting_filing_policy():
    records=tuple(document(status=status,linked_to='rf-1086 original reference')
        for status in DocumentStatus if status!=DocumentStatus.REMOVED)
    prior=replace(document(),income_year=IncomeYear(int(YEAR)-1))
    future=replace(document(),income_year=IncomeYear(int(YEAR)+1))
    result=annual_document_inputs((prior,*records,future),QUERY)
    assert result.company_id==COMPANY and result.income_year==YEAR
    assert result.documents==tuple(sorted(records,key=lambda item:str(item.document_id)))
    assert any(item.status==DocumentStatus.QUARANTINED for item in result.documents)
    assert any(item.status==DocumentStatus.MISSING_ACCEPTED_WARNING for item in result.documents)
    assert any(item.status==DocumentStatus.STAGED and item.content_sha256 is None for item in result.documents)
    with pytest.raises(AttributeError):result.documents=()


def test_successful_empty_current_year_is_scope_bound():
    result=annual_document_inputs((replace(document(),income_year=IncomeYear(int(YEAR)-1)),),QUERY)
    assert result.company_id==COMPANY and result.income_year==YEAR and result.documents==()


@pytest.mark.parametrize('kind',['duplicate','foreign','removed','removal-time','not-tuple','unavailable'])
def test_inconsistent_or_unavailable_enumeration_fails_closed(kind):
    item=document()
    values={'duplicate':(item,item),'foreign':(replace(item,company_id=CompanyId(str(uuid4()))),),
        'removed':(replace(item,status=DocumentStatus.REMOVED),),'removal-time':(replace(item,removed_at=item.created_at),),
        'not-tuple':[item],'unavailable':None}
    with pytest.raises(rf.ShareholderRegisterFilingError):annual_document_inputs(values[kind],QUERY)


def test_existing_owner_decoder_and_query_use_same_connection_then_admission_expires():
    item=document();calls=[]
    class Connection:
        info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        async def execute(self,statement,args):calls.append((statement,args));return self
        async def fetchall(self):return [wire(item)]
    scope=_SourceAdmission(STORE,Connection(),QUERY,AdmissionHarness().identity)
    async def run():
        result=await scope.annual_document_inputs()
        assert result.documents==(item,)
        assert calls==[("select * from documents.list_documents_v1(%s::uuid[], %s)",([str(COMPANY)],str(STORE.actor_id.subject)))]
        scope.close()
        with pytest.raises(rf.ShareholderRegisterFilingError):await scope.annual_document_inputs()
        assert len(calls)==1
    asyncio.run(run())


@pytest.mark.parametrize('invalid',['missing-column','unknown-status','invalid-company'])
def test_malformed_owner_metadata_is_unavailable_not_empty(invalid):
    item=wire(document())
    if invalid=='missing-column':del item['created_at']
    elif invalid=='unknown-status':item['status']='undocumented'
    else:item['company_id']='invalid'
    class Connection:
        info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        async def execute(self,*_):return self
        async def fetchall(self):return [item]
    async def run():
        reader=SupabaseDocumentMetadataTransaction(Connection(),STORE.actor_id)
        with pytest.raises(DocumentsError) as error:await reader.list_documents((COMPANY,))
        assert error.value.code=='DOCUMENT_STORAGE_UNAVAILABLE'
    asyncio.run(run())


def test_metadata_reader_requires_an_active_transaction_before_io():
    class Connection:
        info=SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        async def execute(self,*_):raise AssertionError('no query may run')
    async def run():
        with pytest.raises(DocumentsError):
            await SupabaseDocumentMetadataTransaction(Connection(),STORE.actor_id).list_documents((COMPANY,))
    asyncio.run(run())
