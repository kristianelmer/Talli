"""Validate exact owned documents offline against shipped official 2025 assets."""
from dataclasses import FrozenInstanceError, replace
import base64
import json
from pathlib import Path
import shutil

import pytest

from talli_backend.adapters import company_tax_schemas as schemas
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError, CompanyTaxEnvelopeInput, CompanyTaxReturnDocuments,
    TaxDeliverySource, prepare_tax_delivery, render_company_tax_envelope,
)
from test_company_tax_delivery import raw_source
from test_company_tax_delivery_source import Inputs, read


@pytest.fixture(scope='module')
def validator():
    return schemas.PinnedTax2025Schemas()


def prepared(validator, source=None):
    return prepare_tax_delivery(source or read(Inputs()), party_number='123456',
        current_document_reference='synthetic-current-2025', schema_sha256=validator.schema_sha256)


def rewrap(envelope, **changes):
    changed = replace(envelope, **changes)
    request = render_company_tax_envelope(CompanyTaxEnvelopeInput(
        CompanyTaxReturnDocuments(changed.tax_xml,changed.business_xml),
        changed.source.organization_number, int(changed.source.income_year), 'Talli',
        changed.current_document_reference))
    return replace(changed, envelope_xml=request)


@pytest.mark.parametrize('case', ['no-activity-zero', 'supported-dividend', 'recognized-unsettled'])
def test_exact_supported_documents_validate_against_official_pins_and_proof_is_immutable(validator, case):
    source = read(Inputs()) if case == 'recognized-unsettled' else TaxDeliverySource(**raw_source(case))
    envelope = prepared(validator,source)
    proof = validator.validate(envelope)
    proof.verify(envelope)
    assert proof.schema_sha256 == validator.schema_sha256
    assert proof.envelope_xml_sha256 == envelope.envelope_sha256
    with pytest.raises(FrozenInstanceError): proof.schema_sha256 = 'b'*64
    with pytest.raises(ValueError): proof.verify(replace(envelope,tax_xml=envelope.tax_xml+'\n'))


@pytest.mark.parametrize('change', ['tax-year','business-year','party','org','reference','reference-type','payload','encoding','count','schema','code','category','structure'])
def test_valid_xml_cannot_substitute_other_identity_reference_payload_or_code(validator,change):
    envelope = prepared(validator)
    if change == 'tax-year':
        changed = rewrap(envelope,tax_xml=envelope.tax_xml.replace('<inntektsaar>2025</inntektsaar>', '<inntektsaar>2024</inntektsaar>'))
    elif change == 'business-year':
        changed = rewrap(envelope,business_xml=envelope.business_xml.replace('<inntektsaar>2025</inntektsaar>', '<inntektsaar>2024</inntektsaar>'))
    elif change == 'party':
        changed = rewrap(envelope,business_xml=envelope.business_xml.replace('<partsreferanse>123456</partsreferanse>','<partsreferanse>999999</partsreferanse>'))
    elif change == 'org':
        changed = replace(envelope,envelope_xml=envelope.envelope_xml.replace('<tin>123456789</tin>','<tin>999999999</tin>'))
    elif change == 'reference':
        changed = replace(envelope,envelope_xml=envelope.envelope_xml.replace('synthetic-current-2025','another-current-reference'))
    elif change == 'reference-type':
        changed = replace(envelope,envelope_xml=envelope.envelope_xml.replace('<dokumenttype>skattemeldingUpersonlig</dokumenttype>',
            '<dokumenttype>naeringsspesifikasjon</dokumenttype>'))
    elif change == 'payload':
        original = base64.b64encode(envelope.tax_xml.encode()).decode()
        other = base64.b64encode((envelope.tax_xml+'\n').encode()).decode()
        changed = replace(envelope,envelope_xml=envelope.envelope_xml.replace(original,other))
    elif change == 'encoding':
        changed = replace(envelope,envelope_xml=envelope.envelope_xml.replace('<encoding>utf-8</encoding>','<encoding>UTF-16</encoding>'))
    elif change == 'count':
        first = envelope.envelope_xml.index('    <dokument>')
        end = envelope.envelope_xml.index('    </dokument>',first)+len('    </dokument>')
        changed = replace(envelope,envelope_xml=envelope.envelope_xml[:first]+envelope.envelope_xml[end:])
    elif change == 'schema':
        changed = replace(envelope,schema_sha256='b'*64)
    elif change == 'code':
        changed = rewrap(envelope,business_xml=envelope.business_xml.replace('>1570<','>9999<'))
    elif change == 'category':
        changed = rewrap(envelope,business_xml=envelope.business_xml.replace('>1570<','>6700<'))
    else:
        changed = rewrap(envelope,tax_xml=envelope.tax_xml.replace('  <partsnummer>123456</partsnummer>\n',''))
    assert changed != envelope, 'The regression must actually change the target XML.'
    with pytest.raises(CompanyTaxError): validator.validate(changed)


@pytest.mark.parametrize('reference', ['file:///etc/passwd', 'http://127.0.0.1:1/private', 'https://example.test/private'])
def test_dtd_and_external_entities_are_rejected_without_resolving_them(validator,reference):
    envelope = prepared(validator)
    tax = envelope.tax_xml.replace('?>','?>\n<!DOCTYPE skattemelding [<!ENTITY xxe SYSTEM "'+reference+'">]>',1)
    tax = tax.replace('<partsnummer>123456</partsnummer>','<partsnummer>&xxe;</partsnummer>')
    with pytest.raises(CompanyTaxError): validator.validate(rewrap(envelope,tax_xml=tax))


@pytest.mark.parametrize('target', ['manifest.json','skattemeldingUpersonlig_v5_ekstern.xsd','2025_resultatregnskapOgBalanse.xml'])
def test_changed_manifest_schema_or_code_list_is_unavailable(monkeypatch,tmp_path,target):
    bundle = tmp_path/'bundle'
    shutil.copytree(schemas._BUNDLE,bundle)
    (bundle/target).write_bytes((bundle/target).read_bytes()+b'\n')
    monkeypatch.setattr(schemas,'_BUNDLE',bundle)
    with pytest.raises(CompanyTaxError) as error: schemas.PinnedTax2025Schemas()
    assert error.value.code == 'COMPANY_TAX_DEPENDENCY_UNAVAILABLE'


def test_bundle_manifest_reconciles_exact_resources_and_upstream_license():
    manifest = json.loads((schemas._BUNDLE/'manifest.json').read_bytes())
    assert manifest['sourceCommit'] == '7ac8c6a32238dd0d53e7ac01a6949bb3376f2bba'
    assert set(manifest['files']) | {'manifest.json'} == {path.name for path in schemas._BUNDLE.iterdir()}
    assert (schemas._BUNDLE/'LICENSE').read_text().lstrip().startswith('Apache License')


def test_validation_proof_cannot_be_reused_for_changed_source_with_identical_documents(validator):
    envelope = prepared(validator)
    proof = validator.validate(envelope)
    source = replace(envelope.source,upstream_sha256={**envelope.source.upstream_sha256,'annual':'b'*64})
    with pytest.raises(ValueError): proof.verify(replace(envelope,source=source))
    with pytest.raises(ValueError):
        proof.verify(replace(envelope,current_document_reference='changed-metadata-with-original-XML'))


def test_delivery_projection_groups_every_supported_cost_account_under_official_codes(validator):
    from test_company_tax_delivery_source import entry
    from talli_backend.modules.ledger.public import LedgerEntryKind, LedgerLine
    from talli_backend.shared.kernel import Money
    from xml.etree import ElementTree
    inputs = Inputs()
    for number, account in enumerate(('6420','6700','6705','6720','7770','7790','7795'),start=2):
        inputs.entries += (replace(entry(number),entry_kind=LedgerEntryKind.ADMINISTRATIVE_COST,
            lines=(LedgerLine(account,'Supported cost',Money.nok('100'),Money.nok('0')),
                   LedgerLine('1920','Cost paid',Money.nok('0'),Money.nok('100')))),)
    envelope = prepared(validator,read(inputs))
    validator.validate(envelope)
    costs = ElementTree.fromstring(envelope.business_xml).findall('.//{*}annenDriftskostnad/{*}kostnad')
    values = {row.find('./{*}type/{*}resultatOgBalanseregnskapstype').text:
        row.find('./{*}beloep/{*}beloep/{*}beloep').text for row in costs}
    assert values == {'6400':'100','6700':'300','7700':'300'}
