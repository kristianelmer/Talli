"""A retained review binds the precise artifact and independently current inputs."""
import asyncio
import base64
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from uuid import uuid4

import pytest

from talli_backend.modules.company_tax_filing.public import (
    TaxDeliveryAuthorityMode, approve_tax_delivery_review, decode_tax_delivery_review_approval,
    TaxCurrentDocumentKind,
)
from talli_backend.shared.kernel import Timestamp
from test_company_tax_delivery_preparation import setup


@pytest.fixture(scope='module')
def review_basis():
    _,_,app,command=setup()
    async def prepare():return await (await app.session('synthetic')).prepare_delivery_draft(command)
    draft=asyncio.run(prepare()).draft
    return dict(approval_id=str(uuid4()),draft=draft,approved_by=command.actor_id,
        expected_draft_sha256=draft.sha256,expected_review_sha256=draft.envelope.review_sha256,
        current_source=draft.envelope.source,current_document=draft.current_document,
        current_schema_sha256=draft.envelope.schema_sha256,
        authority_mode=TaxDeliveryAuthorityMode.FINITE_LOOPBACK,authority_context_sha256='c'*64)


def test_review_keeps_one_exact_commitment_and_allows_a_later_observation_of_the_same_original(review_basis):
    current=review_basis['current_document']
    later=replace(current,response=replace(current.response,
        observed_at=Timestamp(current.response.observed_at.value+timedelta(minutes=1))))
    first=approve_tax_delivery_review(**review_basis)
    second=approve_tax_delivery_review(**(review_basis|{'current_document':later}))
    assert first==second and first.sha256==second.sha256
    restored=decode_tax_delivery_review_approval(first.canonical_json,first.sha256)
    assert restored==first and restored.canonical_json==first.canonical_json
    restored.assert_draft(review_basis['draft'])
    assert 'raw_base64' not in first.canonical_json and 'tax_xml' not in first.canonical_json


@pytest.mark.parametrize('change',['draft','review','schema','source','original','party','kind','reference','offline','mode'])
def test_review_rejects_changed_independent_evidence_and_unsupported_authority(review_basis,change):
    values=dict(review_basis);current=values['current_document']
    if change=='draft':values['expected_draft_sha256']='d'*64
    elif change=='review':values['expected_review_sha256']='d'*64
    elif change=='schema':values['current_schema_sha256']='d'*64
    elif change=='source':
        source=values['current_source']
        values['current_source']=replace(source,upstream_sha256=source.upstream_sha256|{'annual':'d'*64})
    elif change=='original':
        values['current_document']=replace(current,response=replace(current.response,
            raw_base64=base64.b64encode(current.response.raw_bytes+b'\n').decode()))
    elif change=='party':values['current_document']=replace(current,party_number='999999')
    elif change=='kind':values['current_document']=replace(current,document_kind=TaxCurrentDocumentKind.FILED)
    elif change=='reference':values['current_document']=replace(current,document_reference='different-current-document')
    elif change=='offline':
        values['draft']=replace(values['draft'],current_document=None)
        values['expected_draft_sha256']=values['draft'].sha256
    elif change=='mode':values['authority_mode']='production'
    with pytest.raises(ValueError):approve_tax_delivery_review(**values)


@pytest.mark.parametrize('change',['space','duplicate','future','unknown','mode','year','scope','digest'])
def test_approval_decoder_refuses_ambiguous_or_altered_records_even_with_recomputed_storage_hash(review_basis,change):
    original=approve_tax_delivery_review(**review_basis)
    raw=original.canonical_json;value=json.loads(raw)
    if change=='space':raw+=' '
    elif change=='duplicate':raw=raw.replace('"version":','"version":"ignored","version":')
    else:
        if change=='future':value['version']='future'
        elif change=='unknown':value['approval']['unowned']=True
        elif change=='mode':value['approval']['authority_mode']='production'
        elif change=='year':value['approval']['income_year']['value']=True
        elif change=='scope':value['approval']['company_id']='untyped-company'
        elif change=='digest':value['approval']['review_sha256']='invalid'
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    with pytest.raises(ValueError):decode_tax_delivery_review_approval(raw,hashlib.sha256(raw.encode()).hexdigest())


def test_approval_cannot_be_reused_for_another_retained_draft_or_authority_context(review_basis):
    approval=approve_tax_delivery_review(**review_basis)
    with pytest.raises(ValueError):approval.assert_draft(replace(review_basis['draft'],filing_id=str(uuid4())))
    changed=approve_tax_delivery_review(**(review_basis|{'authority_context_sha256':'d'*64}))
    assert changed.sha256!=approval.sha256
