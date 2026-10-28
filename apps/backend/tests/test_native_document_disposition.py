"""Changed native boundaries; full PostgreSQL/Storage proof uses the owned runner."""
import asyncio
import json
from uuid import uuid4

import pytest

from talli_backend.adapters.postgres_document_disposition import (
    OwnedNativeDocumentsTarget, _storage_presence,
)
from talli_backend.modules.documents.public import DocumentDisposition,dispose_document


@pytest.mark.parametrize('response',[
    {'status':403,'body':'{}'}, {'status':500,'body':'{}'},
    {'status':404,'body':'{}'}, {'status':400,'body':'{}'},
    {'status':200,'body':'{"version":"different"}'},
    {'status':400,'body':'{"statusCode":"404","error":"AccessDenied","message":"Object not found"}'},
    {'status':404,'body':'not JSON'},
])
def test_unavailable_or_unattributed_storage_never_means_absence(response):
    with pytest.raises(ValueError,match='observation_unavailable'):
        _storage_presence(response,'approved-version')


def test_exact_pinned_storage_absence_and_current_version():
    assert _storage_presence({'status':200,'body':'{"version":"approved-version"}'},'approved-version')
    assert not _storage_presence({'status':400,'body':json.dumps({
        'statusCode':'404','error':'not_found','message':'Object not found'})},'approved-version')


@pytest.mark.parametrize('dsn',[
    'postgresql://talli_native_disposition_0123456789abcdef:private@hosted.example/postgres',
    'postgresql://postgres:private@127.0.0.1/postgres',
    'host=127.0.0.1 hostaddr=192.0.2.1 user=talli_native_disposition_0123456789abcdef password=private dbname=postgres',
    'host=127.0.0.1 user=talli_native_disposition_0123456789abcdef password=private dbname=other',
    'host=127.0.0.1 user=talli_native_disposition_0123456789abcdef password=private dbname=postgres options=-crole=postgres',
])
def test_native_adapter_rejects_hosted_admin_or_ambiguous_connection_before_docker(dsn):
    nonce=uuid4()
    with pytest.raises(ValueError,match='native_operator_connection'):
        OwnedNativeDocumentsTarget(docker='/must-not-run',nonce=str(nonce),label='talli.native.disposition',
            database='unused',storage='unused',network='unused',database_image='unused',storage_image='unused',
            target=str(nonce),database_url=dsn)


def test_document_owner_resumes_only_explicit_known_native_prefix():
    command=DocumentDisposition(uuid4(),uuid4(),uuid4(),2010,'g','a'*64,'cg','b'*64,'erase')
    class Known:
        prepared=False;erased=False
        async def reconcile(self,c):return 'ERASED' if self.erased else 'RESUMABLE'
        async def prepare(self,c):raise AssertionError('known native prefix must not be prepared again')
        async def erase(self,c):self.erased=True
    store=Known();asyncio.run(dispose_document(command,store));assert store.erased


def test_native_current_version_bytes_must_match_approved_selector():
    from talli_backend.adapters.postgres_document_disposition import (
        PostgresDocumentDisposition,native_document_generation,
    )
    company,document,operation,version=uuid4(),uuid4(),uuid4(),str(uuid4())
    key=f'{company}/2010/{document}/fixture.pdf'
    row={'company_id':str(company),'income_year':2010,'content_sha256':'b'*64,
         'storage_key':key,'byte_length':10}
    files=[{'path':'stub/stub/company-documents/'+key+'/'+version,'bytes':10,'sha256':'a'*64}]
    command=DocumentDisposition(operation,company,document,2010,native_document_generation(row,files),'b'*64,'cg','c'*64,'erase')
    state={'companyId':str(company),'generation':'cg','snapshot':{str(document):row},
           'actual':{str(document):row},'receipts':{},'fixtureRecords':[str(document)],
           'objects':{str(document):{'files':files,'storageKey':key,'currentVersion':version}}}
    store=PostgresDocumentDisposition(None)
    store._call=lambda phase,c:state
    # Both metadata and generation commitment are internally consistent. The
    # current bytes still contradict the approved content selector.
    with pytest.raises(ValueError,match='current_bytes_changed'):
        store._state(command)
    with pytest.raises(ValueError,match='current_bytes_changed'):
        asyncio.run(store.prepare(command))


def test_prepare_cannot_attribute_preexisting_unknown_storage_loss():
    from talli_backend.adapters.postgres_document_disposition import PostgresDocumentDisposition
    command=DocumentDisposition(uuid4(),uuid4(),uuid4(),2010,'g','a'*64,'cg','b'*64,'erase')
    store=PostgresDocumentDisposition(None);writes=[]
    store._observe=lambda c:'UNKNOWN'
    store._call=lambda phase,c:writes.append(phase)
    with pytest.raises(ValueError,match='outcome_unknown'):
        asyncio.run(store.prepare(command))
    assert writes==[]
