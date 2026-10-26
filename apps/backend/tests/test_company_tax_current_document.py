"""Inspect current authority originals without loss or invented absence."""
import base64
from dataclasses import replace
from datetime import datetime, UTC
import hashlib
import json
import asyncio
from uuid import uuid4

import pytest
import httpx

from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.adapters.company_tax_authority import CompanyTaxTransport, TAX_BASE
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError, TaxCurrentDocumentResponse, TaxCurrentDocumentKind,
    CompanyTaxReturnAuthorityError,
    TaxDeliveryDraft, decode_tax_delivery_draft,
)
from talli_backend.shared.kernel import IncomeYear, Timestamp, IdempotencyKey
from test_company_tax_delivery import ACTOR
from test_company_tax_schemas import prepared

NS='no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:forespoersel:response:v2'
NOW=Timestamp(datetime(2026,10,26,tzinfo=UTC))


@pytest.fixture(scope='module')
def validator():
    return PinnedTax2025Schemas()


def response(validator,*,tax=None,extra='',locked='',bom=False,kind='skattemeldingUpersonligUtkast'):
    envelope=prepared(validator)
    tax=envelope.tax_xml.encode() if tax is None else tax
    encoded=base64.b64encode(tax).decode()
    raw=(f'<?xml version="1.0" encoding="UTF-8"?><skattemeldingOgNaeringsspesifikasjonforespoerselResponse xmlns="{NS}">'
        '<dokumenter><skattemeldingdokument><id>synthetic-current-2025</id><encoding>utf-8</encoding>'
        f'<content>\n{encoded}\n</content><type>{kind}</type></skattemeldingdokument>{extra}</dokumenter>{locked}'
        '</skattemeldingOgNaeringsspesifikasjonforespoerselResponse>').encode()
    if bom:raw=b'\xef\xbb\xbf'+raw
    return TaxCurrentDocumentResponse(envelope.source.organization_number,IncomeYear(2025),base64.b64encode(raw).decode(),NOW)


@pytest.mark.parametrize('bom',[False,True])
@pytest.mark.parametrize('kind',list(TaxCurrentDocumentKind))
def test_current_identity_is_derived_from_valid_originals_and_preserves_every_response_byte(validator,bom,kind):
    original=response(validator,bom=bom,kind=kind.value)
    current=validator.inspect_current(original)
    assert current.response.raw_bytes==base64.b64decode(original.raw_base64)
    assert current.response.sha256==hashlib.sha256(original.raw_bytes).hexdigest()
    assert current.party_number=='123456'
    assert current.document_reference=='synthetic-current-2025'
    assert current.document_kind is kind
    assert current.tax_xml_sha256==hashlib.sha256(prepared(validator).tax_xml.encode()).hexdigest()
    assert current.schema_sha256==validator.schema_sha256


@pytest.mark.parametrize('change',['namespace','duplicate','missing','reference','encoding','personal',
    'year','tax-namespace','tax-encoding','response-encoding','outer-dtd','inner-dtd','outer-declaration'])
def test_malformed_or_wrong_scope_current_response_is_unavailable(validator,change):
    original=response(validator)
    raw=original.raw_bytes
    tax=prepared(validator).tax_xml.encode()
    if change=='namespace':raw=raw.replace(NS.encode(),b'urn:wrong')
    elif change=='duplicate':
        start=raw.index(b'<skattemeldingdokument>');end=raw.index(b'</skattemeldingdokument>')+len(b'</skattemeldingdokument>')
        raw=raw[:end]+raw[start:end]+raw[end:]
    elif change=='missing':
        start=raw.index(b'<dokumenter>');end=raw.index(b'</dokumenter>')+len(b'</dokumenter>')
        raw=raw[:start]+raw[end:]
    elif change=='reference':raw=raw.replace(b'synthetic-current-2025',b' synthetic-current-2025 ')
    elif change=='encoding':raw=raw.replace(b'<encoding>utf-8',b'<encoding>UTF-16')
    elif change=='personal':raw=raw.replace(b'skattemeldingUpersonligUtkast',b'skattemeldingPersonligUtkast')
    elif change=='year':original=response(validator,tax=tax.replace(b'<inntektsaar>2025',b'<inntektsaar>2024'));raw=original.raw_bytes
    elif change=='tax-namespace':original=response(validator,tax=tax.replace(b'upersonlig:ekstern:v5',b'upersonlig:ekstern:v4'));raw=original.raw_bytes
    elif change=='tax-encoding':original=response(validator,tax=tax+b'\xff');raw=original.raw_bytes
    elif change=='response-encoding':raw+=b'\xff'
    elif change=='outer-dtd':raw=raw.replace(b'?>',b'?><!DOCTYPE x [<!ENTITY external SYSTEM "https://example.test/private">]>',1)
    elif change=='inner-dtd':
        original=response(validator,tax=tax.replace(b'?>',b'?><!DOCTYPE x [<!ENTITY external SYSTEM "file:///private/secret">]>',1));raw=original.raw_bytes
    elif change=='outer-declaration':raw=raw.replace(b'encoding="UTF-8"',b'encoding="ISO-8859-1"',1)
    changed=replace(original,raw_base64=base64.b64encode(raw).decode())
    with pytest.raises(CompanyTaxError) as error:validator.inspect_current(changed)
    assert error.value.code=='COMPANY_TAX_DEPENDENCY_UNAVAILABLE'


@pytest.mark.parametrize('extra,locked',[
    ('<naeringsspesifikasjondokument><id>existing</id><encoding>utf-8</encoding><content>PHgvPg==</content></naeringsspesifikasjondokument>',''),
    ('<utvidetVeiledningdokument><id>guidance</id><encoding>utf-8</encoding><content>PHgvPg==</content></utvidetVeiledningdokument>',''),
    ('','<laasteFelt><laastFeltSkattemelding><sti>locked</sti></laastFeltSkattemelding></laasteFelt>'),
])
def test_unhandled_authority_facts_are_explicitly_blocked_instead_of_dropped(validator,extra,locked):
    with pytest.raises(CompanyTaxError) as error:validator.inspect_current(response(validator,extra=extra,locked=locked))
    assert error.value.code=='COMPANY_TAX_CURRENT_RETURN_UNSUPPORTED'


@pytest.mark.parametrize('extra',[
    b'<underskuddTilFremfoering><fremfoertUnderskuddFraTidligereAar><beloepSomHeltall>100</beloepSomHeltall></fremfoertUnderskuddFraTidligereAar></underskuddTilFremfoering>',
])
def test_valid_unmodelled_tax_carryforward_is_not_silently_replaced_by_zero(validator,extra):
    tax=prepared(validator).tax_xml.encode().replace(b'<inntektOgUnderskudd>',b'<inntektOgUnderskudd>'+extra)
    with pytest.raises(CompanyTaxError) as error:validator.inspect_current(response(validator,tax=tax))
    assert error.value.code=='COMPANY_TAX_CURRENT_RETURN_UNSUPPORTED'


def test_preparation_cannot_discard_or_change_current_share_facts_or_substitute_current_party(validator):
    envelope=prepared(validator)
    original=response(validator)
    current=validator.inspect_current(original)
    validator.validate(envelope,current_document=current)
    changed_tax=envelope.tax_xml.replace('<beloepSomHeltall>1000</beloepSomHeltall>',
        '<beloepSomHeltall>999</beloepSomHeltall>')
    assert changed_tax!=envelope.tax_xml
    other=validator.inspect_current(response(validator,tax=changed_tax.encode()))
    with pytest.raises(CompanyTaxError) as error:validator.validate(envelope,current_document=other)
    assert error.value.code=='COMPANY_TAX_CURRENT_RETURN_UNSUPPORTED'
    with pytest.raises(CompanyTaxError):validator.validate(envelope,current_document=replace(current,party_number='999999'))


def test_v2_draft_retains_current_original_while_v1_storage_bytes_keep_the_old_shape(validator):
    envelope=prepared(validator)
    draft=TaxDeliveryDraft(str(uuid4()),IdempotencyKey('current-document-draft-key'),ACTOR,envelope,validator.validate(envelope))
    legacy=draft.canonical_json
    assert json.loads(legacy)['version']=='company-tax-delivery-draft-v1'
    assert 'current_document' not in json.loads(legacy)['draft']
    assert decode_tax_delivery_draft(legacy,draft.sha256)==draft
    current=validator.inspect_current(response(validator,bom=True))
    bound=replace(draft,current_document=current)
    assert json.loads(bound.canonical_json)['version']=='company-tax-delivery-draft-v2'
    restored=decode_tax_delivery_draft(bound.canonical_json,bound.sha256)
    assert restored==bound and restored.current_document.response.raw_bytes==current.response.raw_bytes
    for changed in [replace(current,document_reference='another-current'),replace(current,schema_sha256='a'*64)]:
        with pytest.raises(ValueError):replace(draft,current_document=changed)


def test_exact_reader_keeps_bom_and_uses_only_the_fixed_scoped_get(validator):
    from test_authority_filing_transports import queue,TAX_TOKEN
    original=response(validator,bom=True)
    transport,requests,pending=queue(httpx.Response(200,content=original.raw_bytes))
    reader=CompanyTaxTransport(TAX_TOKEN,transport=transport)
    result=asyncio.run(reader.fetch_current_document(income_year=2025,company_org_number=original.organization_number))
    assert result.raw_bytes==original.raw_bytes
    assert validator.inspect_current(result).document_reference=='synthetic-current-2025'
    assert not pending and len(requests)==1
    assert requests[0].method=='GET' and str(requests[0].url)==TAX_BASE+'/2025/'+original.organization_number
    assert requests[0].headers['authorization']=='Bearer '+TAX_TOKEN


@pytest.mark.parametrize('body',[b'<x/>\xff',b'opaque-tax-test-token'])
def test_exact_reader_rejects_invalid_utf8_and_reflected_credentials_without_retry(body):
    from test_authority_filing_transports import queue,TAX_TOKEN
    transport,requests,_=queue(httpx.Response(200,content=body))
    reader=CompanyTaxTransport(TAX_TOKEN,transport=transport)
    with pytest.raises(CompanyTaxReturnAuthorityError) as error:
        asyncio.run(reader.fetch_current_document(income_year=2025,company_org_number='123456789'))
    assert error.value.code=='COMPANY_TAX_RESPONSE_INVALID'
    assert len(requests)==1 and TAX_TOKEN not in str(error.value)


@pytest.mark.parametrize('year',[2026,'2025',True])
def test_unsupported_current_generation_never_requests_authority(year):
    from test_authority_filing_transports import queue,TAX_TOKEN
    transport,requests,_=queue()
    with pytest.raises(ValueError):
        asyncio.run(CompanyTaxTransport(TAX_TOKEN,transport=transport).fetch_current_document(
            income_year=year,company_org_number='123456789'))
    assert requests==[]
