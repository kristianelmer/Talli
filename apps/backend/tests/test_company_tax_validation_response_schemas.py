"""Pinned response structure is local proof, never filing or job authority."""
import base64
from dataclasses import replace
from hashlib import sha256
import shutil

import pytest

from talli_backend.adapters import company_tax_response_schemas as resource
from talli_backend.adapters.company_tax_response_schemas import PinnedTaxValidationResponseSchemas
from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose,
    TaxValidationCalculatedDocument,TaxValidationResultCode,
)

NS='no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:response:v2'


def xml(*,result='validertOK',before='',after=''):
    return ('<skattemeldingOgNaeringsspesifikasjonResponse xmlns="'+NS+'">'+before+
        '<resultatAvValidering>'+result+'</resultatAvValidering>'+after+
        '</skattemeldingOgNaeringsspesifikasjonResponse>').encode()


def original(raw):
    return TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.VALIDATION_RESULT,
        base64.b64encode(raw).decode(),'application/xml',200)


def calculated(raw,*,kind='skattemeldingUpersonligEtterBeregning',encoding='utf-8'):
    encoded=base64.b64encode(raw).decode()
    return '<dokument><type>'+kind+'</type><encoding>'+encoding+'</encoding><content>\n'+encoded+'\n</content></dokument>'


def test_validation_pin_is_separate_and_exact_response_bytes_survive_inspection():
    validator=PinnedTaxValidationResponseSchemas()
    raw=b'\xef\xbb\xbf'+xml()+b'\n';value=original(raw);result=validator.inspect(value)
    assert result.schema_sha256=='eaeabcebee3915f31113f026a1d7f854343670c2f45a584691213668d18a71a1'
    assert PinnedTax2025Schemas().schema_sha256=='56668da96711b664843df91d518bb127eb79bddf93c9635765bbd28d35bdda1b'
    assert result.result_code is TaxValidationResultCode.VALIDATED
    assert result.original_sha256==sha256(raw).hexdigest() and value.raw_bytes==raw
    result.verify_original(value)
    with pytest.raises(ValueError):result.verify_original(original(raw+b'\n'))
    assert result.calculated_documents==() and result.guidance_count==0
    assert not hasattr(result,'submitted') and not hasattr(result,'ready')


@pytest.mark.parametrize('code',['validertOK','validertMedFeil'])
def test_guidance_and_deviations_remain_visible_for_both_result_codes(code):
    raw=xml(result=code,before='''<avvikEtterBeregning><avvik><avvikstype>calculation</avvikstype>
        <mottattVerdi>1</mottattVerdi><beregnetVerdi>2</beregnetVerdi></avvik></avvikEtterBeregning>
        <veiledningEtterKontroll><veiledning><veiledningstype>guidance</veiledningstype>
        <hjelpetekst>Kontroller beløpet</hjelpetekst></veiledning></veiledningEtterKontroll>
        <avvikVedValidering><avvik><avvikstype>validation</avvikstype></avvik></avvikVedValidering>''',
        after='<aarsakTilValidertMedFeil>reason one</aarsakTilValidertMedFeil><aarsakTilValidertMedFeil>reason two</aarsakTilValidertMedFeil>')
    result=PinnedTaxValidationResponseSchemas().inspect(original(raw))
    assert result.result_code.value==code
    assert (result.calculation_deviation_count,result.validation_deviation_count,result.guidance_count,result.failure_reason_count)==(1,1,1,2)


def test_calculated_document_decoding_retains_exact_bytes_without_asserting_company_or_year():
    raw=b'\xef\xbb\xbf<calculated year="2026">\xc3\xa5</calculated>\n'
    outer=xml(before='<dokumenter>'+calculated(raw)+'</dokumenter>')
    result=PinnedTaxValidationResponseSchemas().inspect(original(outer))
    assert result.calculated_documents[0].raw_bytes==raw
    assert result.original_sha256==sha256(outer).hexdigest()
    # The common XSD validates an opaque base64 document. This does not prove
    # Talli's supported inner schema/year/party or bind a known validation job.
    assert not hasattr(result,'company_id') and not hasattr(result,'income_year') and not hasattr(result,'job_id')


@pytest.mark.parametrize('defect',['root','namespace','missing-result','unknown-result','duplicate-result','unknown-field',
    'attribute','invalid-order','wrong-encoding','non-utf8-document','empty-document','unknown-document-type','duplicate-document-type',
    'noncanonical-xml','doctype','external-entity','deep','xml-declaration-encoding'])
def test_unsupported_or_unsafe_response_never_produces_positive_inspection(defect):
    raw=xml()
    if defect=='root':raw=raw.replace(b'skattemeldingOgNaeringsspesifikasjonResponse',b'other')
    elif defect=='namespace':raw=raw.replace(NS.encode(),b'urn:foreign')
    elif defect=='missing-result':raw=raw.replace(b'<resultatAvValidering>validertOK</resultatAvValidering>',b'')
    elif defect=='unknown-result':raw=xml(result='submitted')
    elif defect=='duplicate-result':raw=xml(after='<resultatAvValidering>validertOK</resultatAvValidering>')
    elif defect=='unknown-field':raw=xml(after='<accepted>true</accepted>')
    elif defect=='attribute':raw=raw.replace(b' xmlns=',b' accepted="true" xmlns=')
    elif defect=='invalid-order':raw=xml(after='<avvikVedValidering><avvik><avvikstype>x</avvikstype></avvik></avvikVedValidering>')
    elif defect=='wrong-encoding':raw=xml(before='<dokumenter>'+calculated(b'<doc/>',encoding='utf-16')+'</dokumenter>')
    elif defect=='non-utf8-document':raw=xml(before='<dokumenter>'+calculated(b'\xff')+'</dokumenter>')
    elif defect=='empty-document':raw=xml(before='<dokumenter>'+calculated(b'')+'</dokumenter>')
    elif defect=='unknown-document-type':raw=xml(before='<dokumenter>'+calculated(b'<doc/>',kind='unknown')+'</dokumenter>')
    elif defect=='duplicate-document-type':raw=xml(before='<dokumenter>'+calculated(b'<one/>')+calculated(b'<two/>')+'</dokumenter>')
    elif defect=='noncanonical-xml':raw=raw[:-10]
    elif defect=='doctype':raw=b'<!DOCTYPE skattemeldingOgNaeringsspesifikasjonResponse>'+raw
    elif defect=='external-entity':raw=b'<!DOCTYPE skattemeldingOgNaeringsspesifikasjonResponse [<!ENTITY leak SYSTEM "file:///not-an-authorized-resource">]>'+raw.replace(b'validertOK',b'&leak;')
    elif defect=='deep':raw=xml(before='<deep>'*300+'</deep>'*300)
    else:raw=b'<?xml version="1.0" encoding="ISO-8859-1"?>'+raw
    with pytest.raises(CompanyTaxError) as caught:PinnedTaxValidationResponseSchemas().inspect(original(raw))
    assert caught.value.code=='COMPANY_TAX_DEPENDENCY_UNAVAILABLE'


@pytest.mark.parametrize('defect',['manifest','schema','license','missing','manifest-link','schema-link','bundle-link'])
def test_packaged_response_bundle_integrity_is_checked_before_parsing(tmp_path,monkeypatch,defect):
    target=tmp_path/'bundle';shutil.copytree(resource._BUNDLE,target)
    if defect in ('manifest','schema','license'):
        name={'manifest':'manifest.json','schema':resource._XSD,'license':'LICENSE'}[defect]
        with (target/name).open('ab') as output:output.write(b'\n')
    elif defect=='missing':(target/resource._XSD).unlink()
    elif defect in ('manifest-link','schema-link'):
        name='manifest.json' if defect=='manifest-link' else resource._XSD
        (target/name).unlink();(target/name).symlink_to(resource._BUNDLE/name)
    else:
        linked=tmp_path/'linked';linked.symlink_to(target,target_is_directory=True);target=linked
    monkeypatch.setattr(resource,'_BUNDLE',target)
    with pytest.raises(CompanyTaxError):PinnedTaxValidationResponseSchemas()


@pytest.mark.parametrize('purpose',[TaxDeliveryOriginalPurpose.ENVELOPE,TaxDeliveryOriginalPurpose.INSTANCE])
def test_other_original_purposes_cannot_be_promoted_to_a_validation_result(purpose):
    value=original(xml())
    value=replace(value,purpose=purpose,content_type='application/json' if purpose is TaxDeliveryOriginalPurpose.INSTANCE else 'application/xml')
    with pytest.raises(CompanyTaxError):PinnedTaxValidationResponseSchemas().inspect(value)


def test_inspection_bounds_and_calculated_document_types_are_strict():
    result=PinnedTaxValidationResponseSchemas().inspect(original(xml()))
    for value in (True,-1,100001,'0'):
        with pytest.raises(ValueError):replace(result,guidance_count=value)
    with pytest.raises(ValueError):replace(result,result_code='validertOK')
    with pytest.raises(ValueError):TaxValidationCalculatedDocument('unknown',base64.b64encode(b'<doc/>').decode())
