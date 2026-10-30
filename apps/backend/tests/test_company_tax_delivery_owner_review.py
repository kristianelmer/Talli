"""Read the exact owner-review artifact without mutation or provider operations."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json

import pytest

from talli_backend.adapters.company_tax_calculated_schemas import PinnedTax2025CalculatedSchemas
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,TaxDeliveryOwnerReviewQuery,TaxCalculatedDocumentsReview,
    TaxCalculatedDocumentReview,TaxCalculatedReviewField,
)
from talli_backend.shared.kernel import CorrelationId,Timestamp
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_journal_archive import complete_archive
from test_company_tax_delivery_submission import workflow
from test_company_tax_delivery_upload_workflow import upload_workflow
from test_company_tax_delivery_validation_workflow import validation_workflow
from test_company_tax_delivery_confirmation_workflow import confirmation_workflow,validated
from test_company_tax_calculated_schemas import documents,result


async def prepared(fixture,*,complete=True):
    session,service,_,_,state,*_=fixture
    before='<avvikEtterBeregning><avvik><avvikstype>changed</avvikstype><mottattVerdi>1</mottattVerdi>'
    before+='<beregnetVerdi>2</beregnetVerdi></avvik></avvikEtterBeregning>'
    before+='<veiledningEtterKontroll><veiledning><veiledningstype>review</veiledningstype>'
    before+='<hjelpetekst>Kontroller beløpet før du bekrefter.</hjelpetekst></veiledning></veiledningEtterKontroll>'
    state['resultBytes']=result(documents(session.draft),before=before,
        after='<informasjonOmUpersonligSkattesubjekt><erFritattForFormuesskatt>true</erFritattForFormuesskatt></informasjonOmUpersonligSkattesubjekt>').raw_bytes
    command,*_=await validated(fixture);await service.advance_confirmation(session,command)
    if complete:await service.reconcile_confirmation(session,command)
    return TaxDeliveryOwnerReviewQuery(command.company_id,command.income_year,command.actor_id,str(command.filing_id),
        command.expected_approval_sha256,CorrelationId('owner-review-read'))


def test_owner_review_keeps_exact_documents_all_changes_and_warning_text_and_a_stable_identity(confirmation_workflow):
    session,service,_,calls,state,clock,grant=confirmation_workflow
    async def exercise():
        query=await prepared(confirmation_workflow);count=len(calls);events=tuple(session.events)
        artifact=await service.owner_review(session,query)
        assert artifact.response.guidance[0].message=='Kontroller beløpet før du bekrefter.'
        assert artifact.response.calculation_deviations[0].received_value=='1'
        assert artifact.response.calculation_deviations[0].calculated_value=='2'
        assert artifact.response.subject_flags[0].value is True
        assert len(artifact.calculated.documents)==4
        assert artifact.sha256==sha256(artifact.canonical_json.encode()).hexdigest()
        content=json.loads(artifact.canonical_json)
        assert 'observed_at' not in content['review']
        assert content['review']['response']['inspection']['original_sha256']==sha256(state['resultBytes']).hexdigest()
        assert artifact.response_original.raw_bytes==state['resultBytes']
        with pytest.raises(ValueError):replace(artifact,response_original=replace(artifact.response_original,body_base64='Y2hhbmdlZA=='))
        assert artifact==await service.owner_review(session,query)
        clock[0]=Timestamp(grant.expires_at.value+timedelta(seconds=1))
        assert (await service.owner_review(session,query)).sha256==artifact.sha256
        assert tuple(session.events)==events and len(calls)==count
        assert not any(hasattr(artifact,name) for name in ('ready','submitted','accepted','owner_confirmed'))
    asyncio.run(exercise())


def test_owner_review_needs_a_complete_read_proof_not_only_a_successful_put_acknowledgment(confirmation_workflow):
    session,service,_,calls,*_=confirmation_workflow
    async def exercise():
        query=await prepared(confirmation_workflow,complete=False);count=len(calls)
        with pytest.raises(CompanyTaxError):await service.owner_review(session,query)
        assert len(calls)==count
    asyncio.run(exercise())


@pytest.mark.parametrize('change',['owner','mfa','source','approval'])
def test_current_access_source_and_original_approval_are_required_for_owner_review(confirmation_workflow,change):
    session,service,_,calls,*_=confirmation_workflow
    async def exercise():
        query=await prepared(confirmation_workflow);count=len(calls)
        if change=='owner':session.owner=False
        elif change=='mfa':session.fresh=False
        elif change=='source':session.source=replace(session.source,upstream_sha256=session.source.upstream_sha256|{'annual':'d'*64})
        else:query=replace(query,expected_approval_sha256='d'*64)
        with pytest.raises(CompanyTaxError):await service.owner_review(session,query)
        assert len(calls)==count
    asyncio.run(exercise())


@pytest.mark.parametrize('change',['owner','mfa','source'])
def test_owner_review_rechecks_after_xml_inspection_before_disclosing_the_artifact(confirmation_workflow,change,monkeypatch):
    session,service,_,calls,*_=confirmation_workflow
    async def exercise():
        query=await prepared(confirmation_workflow);count=len(calls);original=service._response_schemas.review
        def inspect(value):
            result=original(value)
            if change=='owner':session.owner=False
            elif change=='mfa':session.fresh=False
            else:session.source=replace(session.source,upstream_sha256=session.source.upstream_sha256|{'annual':'d'*64})
            return result
        monkeypatch.setattr(service._response_schemas,'review',inspect)
        with pytest.raises(CompanyTaxError):await service.owner_review(session,query)
        assert len(calls)==count
    asyncio.run(exercise())


def test_calculated_document_review_preserves_empty_leaves_attributes_and_scope_values(review_basis):
    draft=review_basis['draft'];values=documents(draft)
    key='skattemeldingUpersonligEtterBeregning'
    raw=values[key];values[key]=raw.replace(b'<skattemelding ',b'<skattemelding xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="urn:review profile.xsd" ',1)
    assert values[key]!=raw
    value=result(values);review=PinnedTax2025CalculatedSchemas().review_documents(value,draft=draft)
    assert isinstance(review,TaxCalculatedDocumentsReview)
    assert review.inspection.response.original_sha256==sha256(value.raw_bytes).hexdigest()
    for document,original in zip(review.documents,review.inspection.response.calculated_documents):
        assert document.original_sha256==sha256(original.raw_bytes).hexdigest()
        assert document.fields and len({field.path for field in document.fields})==len(document.fields)
    tax=review.documents[0]
    assert any(field.path.endswith('/partsnummer[1]') and field.value==draft.current_document.party_number for field in tax.fields)
    assert any(field.path.endswith('/inntektsaar[1]') and field.value=='2025' for field in tax.fields)
    assert any(field.path.endswith('/@{http://www.w3.org/2001/XMLSchema-instance}schemaLocation') and field.value=='urn:review profile.xsd' for field in tax.fields)
    computed=next(doc for doc in review.documents if doc.document_type=='beregnetSkattUpersonlig')
    assert computed.fields==(TaxCalculatedReviewField('/beregnetSkatt[1]',''),)
    with pytest.raises(ValueError):replace(review,documents=review.documents[:-1])
    with pytest.raises(ValueError):replace(review,documents=tuple(reversed(review.documents)))
    with pytest.raises(ValueError):TaxCalculatedDocumentReview(tax.document_type,tax.original_sha256,(tax.fields[0],tax.fields[0]))


def test_repeated_long_xml_paths_stop_at_the_review_byte_bound_before_materializing_all_fields(review_basis,monkeypatch):
    from lxml import etree
    import talli_backend.adapters.company_tax_calculated_schemas as adapter
    schemas=PinnedTax2025CalculatedSchemas();value=result(documents(review_basis['draft']))
    inspection=schemas.inspect(value,draft=review_basis['draft'])
    # Isolate projection amplification after the already tested XSD inspection.
    root=etree.Element('root');parent=etree.SubElement(root,'a'*2000)
    for _ in range(15000):etree.SubElement(parent,'value').text='1'
    monkeypatch.setattr(schemas,'inspect',lambda *args,**kwargs:inspection)
    monkeypatch.setattr(adapter,'_parse',lambda raw:root)
    count=0;field=adapter.TaxCalculatedReviewField
    def retain(path,value):
        nonlocal count
        count+=1
        return field(path,value)
    monkeypatch.setattr(adapter,'TaxCalculatedReviewField',retain)
    with pytest.raises(CompanyTaxError):schemas.review_documents(value,draft=review_basis['draft'])
    assert count<15000
