"""Fresh bracketing reads bind process actions without classifying signature content."""
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from talli_backend.adapters.annual_accounts_schemas import PinnedAnnualAccountsSchemas
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsDeliveryFrameRecord as Frame,AnnualAccountsFrameKind as Kind,
    AnnualAccountsDeliveryObservation as Observation,AnnualAccountsDeliveryAction as Action,
    inspect_annual_accounts_delivery_frame,decode_annual_accounts_delivery_record,
)
from talli_backend.shared.kernel import Timestamp
from test_annual_accounts_delivery_records import draft,binding
from test_annual_accounts_delivery_originals import original,metadata,Purpose,INSTANCE,MAIN,ACCOUNTS,NOW


def frame(draft,kind=Kind.UPLOAD_REVIEW,*,issues=()):
    body=metadata('Signering' if kind is Kind.SIGN_REVIEW else None if kind is Kind.ARCHIVE else 'Utfylling',archived=kind is Kind.ARCHIVE)
    body['instanceOwner']['organisationNumber']=draft.source.organization_number
    if kind is not Kind.CREATE_TARGET:body['data'][0]['size']=len(draft.main_form_xml.encode())
    if kind in (Kind.UPLOAD_REVIEW,Kind.SIGN_REVIEW,Kind.ARCHIVE):body['data'][1]['size']=len(draft.company_accounts_xml.encode())
    raw=[original(Purpose.INSTANCE,body)]
    if kind is not Kind.CREATE_TARGET:raw.append(original(Purpose.MAIN_FORM,draft.main_form_xml.encode(),data_id=MAIN,media='application/xml'))
    if kind in (Kind.UPLOAD_REVIEW,Kind.SIGN_REVIEW,Kind.ARCHIVE):raw.append(original(Purpose.COMPANY_ACCOUNTS,draft.company_accounts_xml.encode(),data_id=ACCOUNTS,media='application/xml'))
    if kind in (Kind.UPLOAD_REVIEW,Kind.SIGN_REVIEW):raw.append(original(Purpose.VALIDATION,list(issues)))
    if kind in (Kind.SIGN_REVIEW,Kind.ARCHIVE):
        identity=str(uuid4());pdf=b'%PDF-synthetic\x00\xff\n'
        body['data'].append({'id':identity,'dataType':'ref-data-as-pdf','contentType':'application/pdf','size':len(pdf)})
        raw.append(original(Purpose.PDF,pdf,data_id=identity,media='application/pdf'))
    if kind is Kind.ARCHIVE:
        identity=str(uuid4());signature=b'\xffopaque signature content\x00'
        body['data'].append({'id':identity,'dataType':'signature','contentType':'application/json','size':len(signature)})
        raw.append(original(Purpose.SIGNATURE,signature,data_id=identity))
    # Build both metadata originals only after generated references are final.
    raw[0]=original(Purpose.INSTANCE,body)
    if kind is not Kind.CREATE_TARGET:raw.append(original(Purpose.INSTANCE,body))
    observations=tuple(Observation(binding(draft),str(uuid4()),'a'*64,'b'*64,
        replace(row,observed_at=Timestamp(NOW.value+timedelta(seconds=index)),requested_at=Timestamp(NOW.value+timedelta(seconds=index)))) for index,row in enumerate(raw))
    return Frame(binding(draft),str(uuid4()),kind,tuple(row.sha256 for row in observations)),observations


def inspect(draft,value,observations):return inspect_annual_accounts_delivery_frame(value,observations,draft=draft,
    known_instance=INSTANCE,schemas=PinnedAnnualAccountsSchemas())


@pytest.mark.parametrize('kind,action',[(Kind.CREATE_TARGET,Action.UPLOAD_MAIN_FORM),(Kind.MAIN_UPLOADED,Action.UPLOAD_COMPANY_ACCOUNTS),
    (Kind.UPLOAD_REVIEW,Action.CONFIRM),(Kind.SIGN_REVIEW,Action.SIGN)])
def test_complete_frames_only_match_their_named_next_operation(draft,kind,action):
    value,observations=frame(draft,kind);inspection=inspect(draft,value,observations)
    assert inspection.main_data_id==MAIN and inspection.accounts_data_id==ACCOUNTS
    inspection.assert_action(action);inspection.assert_fresh(Timestamp(NOW.value+timedelta(seconds=10)),after=NOW)
    assert decode_annual_accounts_delivery_record(value.canonical_json,value.sha256)==value
    with pytest.raises(ValueError):inspection.assert_action(Action.CREATE_INSTANCE)
    with pytest.raises(ValueError):inspection.assert_fresh(Timestamp(NOW.value+timedelta(seconds=61)),after=NOW)
    with pytest.raises(ValueError):inspection.assert_fresh(Timestamp(NOW.value+timedelta(seconds=10)),after=Timestamp(NOW.value+timedelta(seconds=1)))


def test_validation_errors_remain_reviewable_and_block_the_process_action(draft):
    value,observations=frame(draft,issues=({'severity':1,'code':'BLOCK','description':'Inspect every retained issue.'},))
    inspection=inspect(draft,value,observations)
    assert inspection.has_validation_errors is True and inspection.validation_issues[0]['code']=='BLOCK'
    with pytest.raises(ValueError):inspection.assert_action(Action.CONFIRM)


def test_archive_requires_all_known_originals_and_preserves_opaque_signature_without_acceptance_claim(draft):
    value,observations=frame(draft,Kind.ARCHIVE);inspection=inspect(draft,value,observations)
    assert inspection.signature_data_id and inspection.pdf_data_ids
    assert not any(hasattr(inspection,name) for name in ('signed','submitted','accepted','safe'))
    with pytest.raises(ValueError):inspection.assert_action(Action.SIGN)
    with pytest.raises(ValueError):inspect(draft,replace(value,observation_sha256=value.observation_sha256[:-2]+value.observation_sha256[-1:]),observations)


def test_same_raw_bytes_have_stable_owner_review_hash_but_new_observations_bind_a_new_prerequisite(draft):
    value,observations=frame(draft);inspection=inspect(draft,value,observations)
    changed=tuple(replace(row,observation_id=str(uuid4()),original=replace(row.original,
        observed_at=Timestamp(row.original.observed_at.value+timedelta(seconds=1)),requested_at=Timestamp(row.original.requested_at.value+timedelta(seconds=1)))) for row in observations)
    newer=replace(value,frame_id=str(uuid4()),observation_sha256=tuple(row.sha256 for row in changed))
    next_inspection=inspect(draft,newer,changed)
    assert inspection.review_sha256==next_inspection.review_sha256
    assert inspection.prerequisite_sha256!=next_inspection.prerequisite_sha256


@pytest.mark.parametrize('defect',['missing-reference','metadata-changed','file-bytes','file-id','duplicated-observation','order','extra-file'])
def test_incomplete_changed_or_ambiguous_reads_never_form_a_valid_process_frame(draft,defect):
    value,observations=frame(draft)
    if defect=='missing-reference':observations=observations[:-1]
    elif defect=='duplicated-observation':observations=observations*2
    else:
        if defect=='metadata-changed':
            body=metadata();body['instanceOwner']['organisationNumber']=draft.source.organization_number
            changed=replace(observations[-1],original=replace(original(Purpose.INSTANCE,body),observed_at=observations[-1].original.observed_at))
            observations=(*observations[:-1],changed)
        elif defect=='file-bytes':observations=(observations[0],replace(observations[1],original=replace(observations[1].original,body_base64='Y2hhbmdlZA==')),*observations[2:])
        elif defect=='file-id':observations=(observations[0],replace(observations[1],original=replace(observations[1].original,data_id=str(uuid4()))),*observations[2:])
        elif defect=='order':observations=(observations[0],observations[2],observations[1],*observations[3:])
        else:observations=(*observations[:-1],replace(observations[1],observation_id=str(uuid4())),observations[-1])
        value=replace(value,observation_sha256=tuple(row.sha256 for row in observations))
    with pytest.raises(ValueError):inspect(draft,value,observations)
