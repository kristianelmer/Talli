"""RR process reads preserve bytes without inventing signing or acceptance."""
import base64
from dataclasses import replace
from datetime import UTC,datetime
import hashlib
import json
from uuid import uuid4

import pytest

from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsReadPurpose as Purpose,AnnualAccountsDeliveryOriginal,
    inspect_annual_accounts_instance,inspect_annual_accounts_validation,
)
from talli_backend.shared.kernel import Timestamp

INSTANCE='12345678/10000000-0000-4000-8000-000000000001';ORG='123456789'
MAIN='20000000-0000-4000-8000-000000000002';ACCOUNTS='30000000-0000-4000-8000-000000000003'
NOW=Timestamp(datetime(2026,10,26,tzinfo=UTC))


def original(purpose,raw,*,data_id=None,media=None):
    if not isinstance(raw,bytes):raw=json.dumps(raw,ensure_ascii=False).encode('utf-8')
    return AnnualAccountsDeliveryOriginal(purpose,INSTANCE,data_id,media or 'application/json',base64.b64encode(raw).decode(),NOW)


def metadata(task='Utfylling',*,archived=False):
    return {'id':INSTANCE,'appId':'brg/aarsregnskap-vanlig-202406','instanceOwner':{'organisationNumber':ORG,'partyId':12345678},
        'process':{'currentTask':{'elementId':task,'altinnTaskType':'data' if task=='Utfylling' else 'signing'}} if task else {
            'currentTask':None,'ended':'2026-10-25T23:59:58Z'},
        'status':{'isArchived':archived,**({'archived':'2026-10-25T23:59:59Z'} if archived else {})},
        'data':[{'id':MAIN,'dataType':'Hovedskjema','contentType':'application/xml','size':0},
                {'id':ACCOUNTS,'dataType':'Underskjema','contentType':'application/xml','size':0}]}


@pytest.mark.parametrize('task,archived',[('Utfylling',False),('Signering',False),(None,True)])
def test_exact_known_metadata_uses_pinned_task_ids_and_scan_disabled_types(task,archived):
    raw=b'\xef\xbb\xbf'+json.dumps(metadata(task,archived=archived)).encode()+b'\n'
    value=original(Purpose.INSTANCE,raw);inspection=inspect_annual_accounts_instance(value,organization_number=ORG)
    assert inspection.instance_id==INSTANCE and inspection.task==task and inspection.archived is archived
    assert value.raw_bytes==raw and value.sha256==hashlib.sha256(raw).hexdigest()
    assert inspection.original_sha256==value.sha256 and len(inspection.data)==2
    assert not any(hasattr(inspection,name) for name in ('signed','accepted','submitted','ready'))


@pytest.mark.parametrize('defect',['org','party','app','instance','unknown-task','task-type','ended-active','archive-active','archive-time',
    'missing-process','missing-archive-flag','duplicate-data','extra-under','attachment','mime','size-type','negative-size','pending-scan','unsafe-scan'])
def test_unsupported_or_ambiguous_metadata_never_proves_progress(defect):
    value=metadata()
    if defect=='org':value['instanceOwner']['organisationNumber']='987654321'
    elif defect=='party':value['instanceOwner']['partyId']=True
    elif defect=='app':value['appId']='brg/other'
    elif defect=='instance':value['id']=INSTANCE.replace('12345678','12345679')
    elif defect=='unknown-task':value['process']['currentTask']['elementId']='unknown'
    elif defect=='task-type':value['process']['currentTask']['altinnTaskType']='signing'
    elif defect=='ended-active':value['process']['ended']='2026-10-26T00:00:00Z'
    elif defect=='archive-active':value['status'].update(isArchived=True,archived='2026-10-26T00:00:00Z')
    elif defect=='archive-time':value=metadata(None,archived=True);value['status']['archived']='2026-10-26'
    elif defect=='missing-process':value.pop('process')
    elif defect=='missing-archive-flag':value['status'].pop('isArchived')
    elif defect=='duplicate-data':value['data'][1]['id']=MAIN
    elif defect=='extra-under':value['data'].append(value['data'][1]|{'id':str(uuid4())})
    elif defect=='attachment':value['data'].append({'id':str(uuid4()),'dataType':'Vedlegg','contentType':'application/pdf','size':1})
    elif defect=='mime':value['data'][0]['contentType']='text/html'
    elif defect=='size-type':value['data'][0]['size']=True
    elif defect=='negative-size':value['data'][0]['size']=-1
    elif defect=='pending-scan':value['data'][0]['fileScanResult']='Pending'
    else:value['data'][0]['fileScanResult']='Infected'
    with pytest.raises(ValueError):inspect_annual_accounts_instance(original(Purpose.INSTANCE,value),organization_number=ORG)


def test_opaque_generated_originals_are_exact_bytes_without_signature_or_acceptance_classification():
    raw=b'\xef\xbb\xbf%PDF-synthetic\x00\xff\n'
    value=original(Purpose.PDF,raw,data_id=str(uuid4()),media='application/pdf')
    assert value.raw_bytes==raw and value.sha256==hashlib.sha256(raw).hexdigest()
    assert not any(hasattr(value,name) for name in ('signed','accepted','submitted','safe'))


@pytest.mark.parametrize('body',[[],{'validationIssues':[]},[{'severity':1,'code':'BLOCK'}],
    [{'severity':'Warning','code':'SOFT'}],[{'severity':3,'code':'INFO'}]])
def test_recognized_validation_retains_complete_raw_response(body):
    value=original(Purpose.VALIDATION,body);issues=inspect_annual_accounts_validation(value)
    assert len(issues)==len(body['validationIssues'] if isinstance(body,dict) else body)
    if issues:
        assert issues[0]['code']==body[0]['code']
        with pytest.raises(TypeError):issues[0]['code']='changed'


@pytest.mark.parametrize('body',[{},None,True,[None],[{}],[{'severity':True}],[{'severity':6}],[{'severity':'unknown'}],
    {'validationIssues':[],'hasErrors':True},b'{"validationIssues":[],"validationIssues":[{"severity":1}]}',b'\xff'])
def test_unknown_or_contradictory_validation_does_not_become_empty_success(body):
    value=original(Purpose.VALIDATION,body)
    with pytest.raises(ValueError):inspect_annual_accounts_validation(value)


def test_duplicate_json_or_deep_metadata_is_not_a_known_instance():
    for raw in (json.dumps(metadata()).replace('"appId":','"appId":"ignored","appId":').encode(),
                ('['*100+']'*100).encode()):
        with pytest.raises(ValueError):inspect_annual_accounts_instance(original(Purpose.INSTANCE,raw),organization_number=ORG)


def test_received_headerless_empty_or_failed_reads_preserve_actual_bytes_without_invented_media():
    value=replace(original(Purpose.INSTANCE,b''),http_status=204,content_type=None)
    assert value.raw_bytes==b'' and value.content_type is None and value.sha256==hashlib.sha256(b'').hexdigest()
    with pytest.raises(ValueError):inspect_annual_accounts_instance(value,organization_number=ORG)
    json_value=replace(original(Purpose.INSTANCE,metadata()),content_type='application/json; charset=utf-8')
    assert json_value.content_type=='application/json; charset=utf-8'
    assert inspect_annual_accounts_instance(json_value,organization_number=ORG).instance_id==INSTANCE


def test_future_process_or_archive_times_cannot_prove_observed_completion():
    value=metadata(None,archived=True);value['process']['ended']='2099-01-01T00:00:00Z';value['status']['archived']='2099-01-01T00:00:01Z'
    with pytest.raises(ValueError):inspect_annual_accounts_instance(original(Purpose.INSTANCE,value),organization_number=ORG)
