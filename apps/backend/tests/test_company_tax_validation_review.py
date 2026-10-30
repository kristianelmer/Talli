"""Every authority warning/change remains reviewable without changing V4 bytes."""
from dataclasses import FrozenInstanceError,replace
from hashlib import sha256
from datetime import datetime,UTC
from base64 import b64encode

import pytest

from talli_backend.adapters.company_tax_response_schemas import PinnedTaxValidationResponseSchemas
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,TaxValidationDeviation,TaxValidationGuidance,TaxValidationSubjectFlag,
    TaxDeliveryReadReference,TaxDeliveryValidationPrerequisite,TaxCalculatedDocumentsInspection,
    TaxValidationResponseInspection,TaxValidationCalculatedDocument,TaxValidationResultCode,
    TaxDeliveryConfirmationPrerequisite,TaxDeliveryMutationRequest,TaxMutationKind,decode_tax_delivery_mutation_request,
)
from talli_backend.shared.kernel import Timestamp,CompanyId,IncomeYear
from test_company_tax_validation_response_schemas import xml,original


def full_response(code='validertOK'):
    calc='''<avvikEtterBeregning><avvik><avvikstype>calculation</avvikstype><forekomstidentifikator>row-1</forekomstidentifikator>
        <mottattVerdi>1200.50</mottattVerdi><beregnetVerdi>1199.00</beregnetVerdi><avvikIVerdi>-1.50</avvikIVerdi>
        <mottattTekst>Før</mottattTekst><beregnetTekst>Etter</beregnetTekst><sti>/beløp</sti><oevrigInformasjon>Kontroller &amp; behold</oevrigInformasjon>
        </avvik><avvik><avvikstype/></avvik></avvikEtterBeregning>'''
    guidance='''<veiledningEtterKontroll><veiledning><veiledningstype>guidance</veiledningstype><forekomstidentifikator>row-2</forekomstidentifikator>
        <hjelpetekst>Ærlig kontroll: &lt;b&gt;økt beløp&lt;/b&gt;</hjelpetekst><betjeningsstrategi>review</betjeningsstrategi><sti>/andre/å</sti></veiledning>
        <veiledning><veiledningstype>guidance</veiledningstype><hjelpetekst/></veiledning></veiledningEtterKontroll>'''
    validation='<avvikVedValidering><avvik><avvikstype>validation</avvikstype><mottattTekst>feil</mottattTekst></avvik></avvikVedValidering>'
    after='<aarsakTilValidertMedFeil>Første årsak</aarsakTilValidertMedFeil><aarsakTilValidertMedFeil/>'
    flags=[('erFritattForFormuesskatt',' true '),('erOmfattetAvSaerreglerForKraftforetak','false'),
        ('erOmfattetAvPetroleumsskatteloven','1'),('erOmfattetAvRederiskatteordningen','0'),
        ('erOmfattetAvFinansskattPaaLoennOgOverskudd',' false '),('harLeveringsfritak','true')]
    after+='<informasjonOmUpersonligSkattesubjekt>'+''.join('<'+name+'>'+value+'</'+name+'>' for name,value in flags)+'</informasjonOmUpersonligSkattesubjekt>'
    return original(b'\xef\xbb\xbf \n'+xml(result=code,before=calc+guidance+validation,after=after)+b'\n')


@pytest.mark.parametrize('code',['validertOK','validertMedFeil'])
def test_review_retains_every_change_warning_failure_and_subject_flag_without_success_claim(code):
    value=full_response(code);review=PinnedTaxValidationResponseSchemas().review(value)
    assert review.inspection.original_sha256==sha256(value.raw_bytes).hexdigest()
    assert review.inspection.result_code.value==code
    first,second=review.calculation_deviations
    assert first==TaxValidationDeviation('calculation','row-1','1200.50','1199.00','-1.50','Før','Etter','/beløp','Kontroller & behold')
    assert second.type_code=='' and second.received_value is None
    assert review.validation_deviations==(TaxValidationDeviation('validation',received_text='feil'),)
    assert review.guidance==(TaxValidationGuidance('guidance','row-2','Ærlig kontroll: <b>økt beløp</b>','review','/andre/å'),
        TaxValidationGuidance('guidance',message=''))
    assert review.failure_reasons==('Første årsak','')
    assert [flag.value for flag in review.subject_flags]==[True,False,True,False,False,True]
    assert review==PinnedTaxValidationResponseSchemas().review(value)
    review.verify_original(value)
    assert review.sha256==sha256(review.canonical_json.encode()).hexdigest()
    assert not any(hasattr(review,name) for name in ('ready','submitted','accepted','owner_confirmed'))
    with pytest.raises(FrozenInstanceError):review.guidance=()


@pytest.mark.parametrize('collection',['calculation_deviations','validation_deviations','guidance','failure_reasons'])
def test_no_counted_review_item_may_be_omitted_or_replaced_with_untyped_caller_data(collection):
    review=PinnedTaxValidationResponseSchemas().review(full_response())
    for changed in ((),list(getattr(review,collection)),tuple({} for _ in getattr(review,collection))):
        with pytest.raises(ValueError):replace(review,**{collection:changed})


def test_xml_character_normalization_does_not_rewrite_the_original():
    value=original(b'\xef\xbb\xbf'+xml(before='<veiledningEtterKontroll><veiledning><veiledningstype>x</veiledningstype>'
        '<hjelpetekst>linje 1\r\nlinje 2</hjelpetekst></veiledning></veiledningEtterKontroll>')+b'\r\n')
    before=value.raw_bytes;review=PinnedTaxValidationResponseSchemas().review(value)
    assert review.guidance[0].message=='linje 1\nlinje 2'
    assert value.raw_bytes==before and review.inspection.original_sha256==sha256(before).hexdigest()
    changed=replace(value,body_base64=b64encode(before+b'\n').decode())
    with pytest.raises(ValueError):review.verify_original(changed)


def test_personal_subject_information_cannot_disappear_from_a_company_owner_review():
    for body in ('<informasjonOmPersonligSkattesubjekt/>','<informasjonOmPersonligSkattesubjekt><sambeskattesMedEktefelle>true</sambeskattesMedEktefelle></informasjonOmPersonligSkattesubjekt>'):
        value=original(xml(after=body))
        assert PinnedTaxValidationResponseSchemas().inspect(value)
        with pytest.raises(CompanyTaxError):PinnedTaxValidationResponseSchemas().review(value)


@pytest.mark.parametrize('value',[True,1,{},None])
def test_required_type_codes_and_optional_texts_are_exact_strings(value):
    with pytest.raises(ValueError):TaxValidationDeviation(value)
    with pytest.raises(ValueError):TaxValidationGuidance(value)
    if value is not None:
        with pytest.raises(ValueError):TaxValidationDeviation('x',received_value=value)
        with pytest.raises(ValueError):TaxValidationGuidance('x',message=value)


def test_subject_flags_are_closed_boolean_and_unambiguous():
    for name,value in [('ready',True),('harLeveringsfritak',1),('harLeveringsfritak','true')]:
        with pytest.raises(ValueError):TaxValidationSubjectFlag(name,value)
    review=PinnedTaxValidationResponseSchemas().review(full_response())
    with pytest.raises(ValueError):replace(review,subject_flags=(review.subject_flags[0],review.subject_flags[0]))


def test_v4_preparation_request_bytes_stay_frozen_when_owner_review_details_are_added():
    now=Timestamp(datetime(2026,10,26,tzinfo=UTC));company=CompanyId('10000000-0000-4000-8000-000000000001');year=IncomeYear(2025)
    instance='123456/10000000-0000-4000-8000-000000000004';data='10000000-0000-4000-8000-000000000005'
    ref=TaxDeliveryReadReference('b'*64,'c'*64,now);clean=TaxDeliveryValidationPrerequisite(instance,data,ref,ref,now,now)
    response=TaxValidationResponseInspection('eaeabcebee3915f31113f026a1d7f854343670c2f45a584691213668d18a71a1','f'*64,
        TaxValidationResultCode.VALIDATED,0,0,0,0,tuple(TaxValidationCalculatedDocument(k,b64encode(v).decode()) for k,v in (
            ('skattemeldingUpersonligEtterBeregning',b'<tax/>'),('naeringsspesifikasjonEtterBeregning',b'<business/>'))))
    calculated=TaxCalculatedDocumentsInspection('c9631dcb56397a2e9632f9a8339d4060aa8f3ae6f58c7bf35b7cc19df5e77769','d'*64,company,year,'123456',response)
    proof=TaxDeliveryConfirmationPrerequisite(clean,'e'*64,ref,ref,calculated,now,now)
    request=TaxDeliveryMutationRequest('10000000-0000-4000-8000-000000000002',company,year,'999888777','a'*64,
        TaxMutationKind.PREPARE_CONFIRMATION,instance,'',confirmation_prerequisite=proof)
    assert request.sha256=='c27967ad4ac40f68480909850b91022f6d2fe26e565df8a0d1fb7c0f0bf2db21'
    assert decode_tax_delivery_mutation_request(request.canonical_json,request.sha256)==request
