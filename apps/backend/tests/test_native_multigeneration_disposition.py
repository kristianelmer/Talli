"""A later prepared history must be intact before an earlier erase starts."""
import json
from uuid import uuid4

import pytest

from talli_backend.adapters.postgres_document_disposition import PostgresDocumentDisposition
from talli_backend.modules.documents.public import DocumentDisposition


@pytest.mark.parametrize('fault',['missing_history','metadata_forbidden','metadata_version_changed','unattributed_generation'])
def test_later_prepared_record_unknown_prevents_first_delete(fault):
    company,first,later=uuid4(),uuid4(),uuid4()
    versions={str(first):str(uuid4()),str(later):str(uuid4())}
    def item(record):
        key=f'{company}/2010/{record}/document.pdf'
        file={'path':'stub/stub/company-documents/'+key+'/'+versions[str(record)],'bytes':10,'sha256':'a'*64}
        return {'storageKey':key,'currentVersion':versions[str(record)],'files':[file]}
    objects={str(first):item(first),str(later):item(later)}
    missing={'path':'stub/stub/company-documents/'+objects[str(later)]['storageKey']+'/'+str(uuid4()),'bytes':9,'sha256':'b'*64}
    objects[str(later)]['files'].append(missing)
    actual=[objects[str(first)]['files'][0],objects[str(later)]['files'][0]]
    command=DocumentDisposition(uuid4(),company,first,2010,'g','a'*64,'cg','c'*64,'erase')
    value={'objects':objects,'receipts':{str(id):{'state':'prepared','plan_sha256':'c'*64} for id in (first,later)},'fixtureRecords':[str(first),str(later)]}
    responses={o['storageKey']:{'status':200,'body':json.dumps({'version':o['currentVersion']})} for o in objects.values()}
    if fault!='missing_history':actual.append(missing)
    if fault=='metadata_forbidden':responses[objects[str(later)]['storageKey']]={'status':403,'body':'{}'}
    if fault=='metadata_version_changed':responses[objects[str(later)]['storageKey']]={'status':200,'body':json.dumps({'version':str(uuid4())})}
    if fault=='unattributed_generation':actual.append({'path':missing['path']+'-unknown','bytes':1,'sha256':'d'*64})
    writes=[]
    class Target:
        def objects(self,**request):
            if request['action']=='manifest':return actual
            if request['action']=='inventory':return {'files':actual,'objects':responses}
            if request.get('method')=='DELETE':writes.append(request);return {'status':500,'body':'{}'}
            return responses[objects[str(first)]['storageKey']]
    store=PostgresDocumentDisposition(Target())
    store._state=lambda c:(value,{'storage_key':objects[str(first)]['storageKey']},objects[str(first)])
    with pytest.raises(ValueError):store._erase(command)
    assert writes==[], 'later prepared history loss must be found before ANY delete'


def test_native_inventory_bound_fails_before_read_or_write():
    store=PostgresDocumentDisposition(None)
    with pytest.raises(ValueError,match='inventory_bound'):
        store._fence((object(),)*257)
