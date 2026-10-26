"""Calculated XML scope and every returned supported document stay explicit."""
import base64
from dataclasses import FrozenInstanceError,replace
from hashlib import sha256
import shutil

import pytest
from lxml import etree

from talli_backend.adapters import company_tax_calculated_schemas as resource
from talli_backend.adapters.company_tax_calculated_schemas import PinnedTax2025CalculatedSchemas
from talli_backend.adapters.company_tax_xml import _compile_packaged_schema
from talli_backend.modules.company_tax_filing.public import CompanyTaxError,TaxValidationResultCode
from test_company_tax_delivery_approval import review_basis
from test_company_tax_validation_response_schemas import xml,original,calculated


@pytest.fixture(scope='module')
def validator():return PinnedTax2025CalculatedSchemas()


def documents(draft,*,optional=True):
    party=draft.current_document.party_number
    values={
        'skattemeldingUpersonligEtterBeregning':draft.envelope.tax_xml.encode(),
        'naeringsspesifikasjonEtterBeregning':draft.envelope.business_xml.encode(),
    }
    if optional:
        values|={
            'beregnetSkattUpersonlig':b'<beregnetSkatt xmlns="urn:no:skatteetaten:fastsetting:formueinntekt:upersonlig:beregnetskatt:v6"/>',
            'summertSkattegrunnlagForVisningUpersonlig':(
                '<summertSkattegrunnlagForVisningUpersonlig xmlns="urn:no:skatteetaten:fastsetting:formueinntekt:upersonlig:summertskattegrunnlagforvisning:v4">'
                '<partsnummer>'+party+'</partsnummer><inntektsaar>2025</inntektsaar></summertSkattegrunnlagForVisningUpersonlig>').encode(),
        }
    return values


def result(values,*,code='validertOK',after='',before=''):
    return original(b'\xef\xbb\xbf'+xml(result=code,before='<dokumenter>'+''.join(
        calculated(raw,kind=kind) for kind,raw in values.items())+'</dokumenter>'+before,after=after)+b'\n')


@pytest.mark.parametrize('optional',[False,True])
@pytest.mark.parametrize('code',['validertOK','validertMedFeil'])
def test_exact_calculated_pair_and_optional_display_documents_are_inspected_without_acceptance(review_basis,validator,optional,code):
    draft=review_basis['draft'];values=documents(draft,optional=optional)
    # BOM/whitespace in an inner statutory document are significant originals.
    tax='skattemeldingUpersonligEtterBeregning';values[tax]=b'\xef\xbb\xbf'+values[tax]+b'\n'
    value=result(values,code=code,before='<veiledningEtterKontroll><veiledning><veiledningstype>review</veiledningstype>'
        '<hjelpetekst>Kontroller</hjelpetekst></veiledning></veiledningEtterKontroll>')
    proof=validator.inspect(value,draft=draft)
    assert proof.schema_sha256=='c9631dcb56397a2e9632f9a8339d4060aa8f3ae6f58c7bf35b7cc19df5e77769'
    assert proof.response.result_code is TaxValidationResultCode(code) and proof.response.guidance_count==1
    assert proof.response.original_sha256==sha256(value.raw_bytes).hexdigest()
    assert {item.document_type:item.raw_bytes for item in proof.response.calculated_documents}==values
    assert proof.draft_sha256==draft.sha256 and proof.party_number==draft.current_document.party_number
    proof.assert_original(value,draft)
    assert not hasattr(proof,'submitted') and not hasattr(proof,'ready') and not hasattr(proof,'accepted')
    assert proof.sha256==sha256(proof.canonical_json.encode()).hexdigest()
    with pytest.raises(FrozenInstanceError):proof.party_number='other'


@pytest.mark.parametrize('kind',['skattemeldingUpersonligEtterBeregning','naeringsspesifikasjonEtterBeregning',
    'summertSkattegrunnlagForVisningUpersonlig'])
@pytest.mark.parametrize('change',['year','party','namespace','structure','encoding','doctype','missing'])
def test_each_scope_bearing_document_must_match_the_pinned_year_party_and_schema(review_basis,validator,kind,change):
    draft=review_basis['draft'];values=documents(draft);raw=values[kind]
    if change=='year':values[kind]=raw.replace(b'>2025<',b'>2024<')
    elif change=='party':values[kind]=raw.replace(draft.current_document.party_number.encode(),b'999999')
    elif change=='namespace':values[kind]=raw.replace(b'urn:no:skatteetaten:',b'urn:foreign:')
    elif change=='structure':values[kind]=raw.replace(b'inntektsaar',b'unknownField')
    elif change=='encoding':values[kind]=raw.replace(b'UTF-8',b'ISO-8859-1') if b'UTF-8' in raw else b'<?xml version="1.0" encoding="ISO-8859-1"?>'+raw
    elif change=='doctype':values[kind]=b'<!DOCTYPE forbidden>'+raw
    else:del values[kind]
    if change=='missing' and kind=='summertSkattegrunnlagForVisningUpersonlig':
        assert validator.inspect(result(values),draft=draft);return
    with pytest.raises(CompanyTaxError):validator.inspect(result(values),draft=draft)


@pytest.mark.parametrize('kind',['beregnetSkattPersonlig','beregnetSkattUpersonligSvalbard',
    'beregnetSkattUpersonligPetroleum','selskapsmeldingSdfEtterBeregning','summertSkattegrunnlagForVisningPersonlig'])
def test_supported_pair_does_not_hide_any_unsupported_document(review_basis,validator,kind):
    draft=review_basis['draft'];values=documents(draft);values[kind]=b'<unsupported/>'
    with pytest.raises(CompanyTaxError):validator.inspect(result(values),draft=draft)


@pytest.mark.parametrize('change',['namespace','unknown-field','unsafe-import','non-utf8'])
def test_computed_tax_has_a_schema_but_no_invented_intrinsic_party_or_year(review_basis,validator,change):
    draft=review_basis['draft'];values=documents(draft)
    raw=values['beregnetSkattUpersonlig']
    if change=='namespace':raw=raw.replace(b':v6',b':v5')
    elif change=='unknown-field':raw=raw.replace(b'/>',b'><partsnummer>999999</partsnummer></beregnetSkatt>')
    elif change=='unsafe-import':raw=b'<!DOCTYPE beregnetSkatt SYSTEM "file:///private/not-authorized">'+raw
    else:raw=b'<?xml version="1.0" encoding="ISO-8859-1"?>'+raw
    values['beregnetSkattUpersonlig']=raw
    with pytest.raises(CompanyTaxError):validator.inspect(result(values),draft=draft)


@pytest.mark.parametrize('change',['code','category'])
def test_calculated_business_codes_use_the_existing_pinned_list_and_occurrence_categories(review_basis,validator,change):
    draft=review_basis['draft'];values=documents(draft)
    raw=values['naeringsspesifikasjonEtterBeregning']
    changed=raw.replace(b'>1570<',b'>9999<' if change=='code' else b'>6700<')
    assert raw!=changed
    values['naeringsspesifikasjonEtterBeregning']=changed
    with pytest.raises(CompanyTaxError):validator.inspect(result(values),draft=draft)


@pytest.mark.parametrize('field',resource._UNSUPPORTED_REGIMES)
@pytest.mark.parametrize('value',['true','1',' true ','\n1\t'])
def test_unsupported_tax_regimes_cannot_be_ignored_when_documents_otherwise_match(review_basis,validator,field,value):
    draft=review_basis['draft']
    after='<informasjonOmUpersonligSkattesubjekt><'+field+'>'+value+'</'+field+'></informasjonOmUpersonligSkattesubjekt>'
    with pytest.raises(CompanyTaxError):validator.inspect(result(documents(draft),after=after),draft=draft)


def test_normal_company_tax_metadata_is_preserved_but_personal_metadata_stops_company_confirmation(review_basis,validator):
    draft=review_basis['draft'];values=documents(draft)
    normal='<informasjonOmUpersonligSkattesubjekt><erFritattForFormuesskatt>true</erFritattForFormuesskatt>'
    normal+='<erOmfattetAvPetroleumsskatteloven>false</erOmfattetAvPetroleumsskatteloven></informasjonOmUpersonligSkattesubjekt>'
    value=result(values,after=normal);validator.inspect(value,draft=draft).assert_original(value,draft)
    with pytest.raises(CompanyTaxError):validator.inspect(result(values,after='<informasjonOmPersonligSkattesubjekt/>'),draft=draft)


@pytest.mark.parametrize('target',['manifest.json',resource._COMPUTED_XSD,resource._SUMMARY_XSD,resource._TYPE_XSD,'LICENSE'])
@pytest.mark.parametrize('change',['bytes','missing','link'])
def test_every_calculated_schema_dependency_is_pinned_and_must_be_a_real_file(tmp_path,monkeypatch,target,change):
    bundle=tmp_path/'bundle';shutil.copytree(resource._BUNDLE,bundle);path=bundle/target
    if change=='bytes':path.write_bytes(path.read_bytes()+b'\n')
    else:
        path.unlink()
        if change=='link':path.symlink_to(resource._BUNDLE/target)
    monkeypatch.setattr(resource,'_BUNDLE',bundle)
    with pytest.raises(CompanyTaxError):PinnedTax2025CalculatedSchemas()


@pytest.mark.parametrize('location',['file:///etc/passwd','https://example.test/private','../typekatalog_v2.xsd','other/typekatalog_v2.xsd'])
def test_schema_import_resolver_has_no_network_file_or_basename_fallback(location):
    raw=resource._BUNDLE.joinpath(resource._COMPUTED_XSD).read_bytes().replace(b'typekatalog/typekatalog_v2.xsd',location.encode())
    with pytest.raises((ValueError,etree.XMLSchemaParseError)):
        _compile_packaged_schema(raw,{'typekatalog/typekatalog_v2.xsd':resource._BUNDLE.joinpath(resource._TYPE_XSD).read_bytes()})


def test_calculated_inspection_cannot_be_reused_with_changed_original_or_draft(review_basis,validator):
    draft=review_basis['draft'];value=result(documents(draft));proof=validator.inspect(value,draft=draft)
    changed=replace(value,body_base64=base64.b64encode(value.raw_bytes+b'\n').decode())
    with pytest.raises(ValueError):proof.assert_original(changed,draft)
    with pytest.raises(ValueError):replace(proof,draft_sha256='d'*64).assert_original(value,draft)
    forged=replace(draft,current_document=replace(draft.current_document,party_number='999999'))
    with pytest.raises(CompanyTaxError):validator.inspect(value,draft=forged)
