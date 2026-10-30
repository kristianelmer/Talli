"""Exact public constraints remain local evidence, never filing permission."""
from dataclasses import FrozenInstanceError
from hashlib import sha256
import json
import shutil

import pytest

from talli_backend.adapters.annual_accounts_schemas import PinnedAnnualAccountsSchemas
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsSource,AnnualAccountsRenderInput,build_annual_accounts,render_annual_accounts,AnnualAccountsError,
)


@pytest.fixture(scope='module')
def schemas():return PinnedAnnualAccountsSchemas()


@pytest.fixture
def documents():
    source=AnnualAccountsSource(2025,{'confirmations':[],'annual_full_time_equivalents':0},())
    return render_annual_accounts(AnnualAccountsRenderInput(build_annual_accounts(source),'123456789','Synthetic Accounts AS',
        'owner@example.test','2026-06-30','Synthetic Person'))


def test_original_renderer_pair_satisfies_pinned_public_constraints_without_changing_bytes(schemas,documents):
    main=b'\xef\xbb\xbf'+documents.main_form_xml.encode()+b'\n';accounts=documents.company_accounts_xml.encode()
    value=schemas.validate_pair(main,accounts,organization_number='123456789',income_year=2025)
    assert value.main_form_sha256==sha256(main).hexdigest() and value.company_accounts_sha256==sha256(accounts).hexdigest()
    assert value.schema_sha256=='04653f5ef226df749e5d9cd7a66dd5c061de85c2c1a7f44ce7c12cea3e1faa49'
    assert not any(hasattr(value,name) for name in ('submitted','accepted','ready','signed'))
    with pytest.raises(FrozenInstanceError):value.income_year=2024


@pytest.mark.parametrize('defect',['organization','year','period','orid','format','currency','namespace','duplicate','unknown','doctype','pi','nonutf8','attribute','date'])
def test_changed_scope_or_unrecognized_xml_never_produces_an_inspection(schemas,documents,defect):
    main=documents.main_form_xml.encode();accounts=documents.company_accounts_xml.encode()
    if defect=='organization':main=main.replace(b'123456789',b'987654321')
    elif defect=='year':main=main.replace(b'>2025<',b'>2024<')
    elif defect=='period':main=main.replace(b'2025-01-01',b'2025-02-01')
    elif defect=='orid':main=main.replace(b'orid="18"',b'orid="19"')
    elif defect=='format':main=main.replace(b'dataFormatId="1266"',b'dataFormatId="9999"')
    elif defect=='currency':accounts=accounts.replace(b'>NOK<',b'>EUR<')
    elif defect=='namespace':accounts=accounts.replace(b'http://schema.brreg.no/regnsys/aarsregnskap_vanlig/underskjema',b'urn:foreign')
    elif defect=='duplicate':main=main.replace(b'</enhet>',b'<navn orid="1">duplicate</navn></enhet>')
    elif defect=='unknown':main=main.replace(b'</melding>',b'<unknown/></melding>')
    elif defect=='doctype':main=b'<!DOCTYPE melding [<!ENTITY x SYSTEM "file:///etc/passwd">]>'+main.split(b'?>',1)[1]
    elif defect=='pi':main=main.replace(b'</melding>',b'<?external processing?></melding>')
    elif defect=='attribute':main=main.replace(b'dataFormatId="1266"',b'dataFormatId="1266" extra="ignored"')
    elif defect=='date':main=main.replace(b'2026-06-30',b'2026-02-31')
    else:main=main.replace(b'encoding="UTF-8"',b'encoding="ISO-8859-1"')
    with pytest.raises(AnnualAccountsError):schemas.validate_pair(main,accounts,organization_number='123456789',income_year=2025)


@pytest.mark.parametrize('name',['manifest.json','Hovedskjema.json','Underskjema.json','applicationmetadata.json','process.bpmn'])
@pytest.mark.parametrize('change',['bytes','link'])
def test_no_changed_or_linked_resource_can_silently_select_a_new_constraint_generation(tmp_path,monkeypatch,name,change):
    from talli_backend.adapters import annual_accounts_schemas as resource
    bundle=tmp_path/'pinned';shutil.copytree(resource._BUNDLE,bundle)
    path=bundle/name
    if change=='bytes':path.write_bytes(path.read_bytes()+b'\n')
    else:
        target=tmp_path/('original-'+name);target.write_bytes(path.read_bytes());path.unlink();path.symlink_to(target)
    monkeypatch.setattr(resource,'_BUNDLE',bundle)
    with pytest.raises(AnnualAccountsError):PinnedAnnualAccountsSchemas()


def test_bounds_and_strict_year_do_not_become_empty_success(schemas,documents):
    for main,year in [(b' '*(8*1024*1024+1),2025),(documents.main_form_xml.encode(),True),
                      (documents.main_form_xml.encode(),2024)]:
        with pytest.raises(AnnualAccountsError):schemas.validate_pair(main,documents.company_accounts_xml.encode(),organization_number='123456789',income_year=year)


@pytest.mark.parametrize('attribute',['xsi:schemaLocation="http://schema.brreg.no/regnsys/aarsregnskap_vanlig https://outside.example/model.xsd"',
    'xsi:noNamespaceSchemaLocation="https://outside.example/model.xsd"',
    'xsi:type="RR0002H_M"'])
def test_schema_instance_hints_are_not_accepted_as_packet_content(schemas,documents,attribute):
    main=documents.main_form_xml.replace('dataFormatId="1266"',attribute+' dataFormatId="1266"').encode()
    with pytest.raises(AnnualAccountsError):schemas.validate_pair(main,documents.company_accounts_xml.encode(),organization_number='123456789',income_year=2025)


@pytest.mark.parametrize('insertion',[('<morselskap orid="4168">nei</morselskap>',
    '<morselskap orid="4168">nei</morselskap><konsernregnskap orid="25943">ja</konsernregnskap>'),
    ('</regnskapsprinsipper>','<forenkletIFRS orid="36639">ja</forenkletIFRS></regnskapsprinsipper>')])
def test_unmodeled_optional_branches_cannot_contradict_the_supported_profile(schemas,documents,insertion):
    from talli_backend.adapters import annual_accounts_schemas as resource
    main=documents.main_form_xml.replace(*insertion).encode()
    schemas._schemas[0].assertValid(resource._parse(main))  # Reach the local profile guard, not an invalid upstream orid.
    with pytest.raises(AnnualAccountsError):schemas.validate_pair(main,documents.company_accounts_xml.encode(),organization_number='123456789',income_year=2025)


@pytest.mark.parametrize('change',['root-keyword','reference-facet','composition-sibling','namespace-form'])
def test_constraint_compiler_rejects_keywords_it_cannot_translate_in_their_context(change):
    from talli_backend.adapters import annual_accounts_schemas as resource
    model=json.loads((resource._BUNDLE/'Hovedskjema.json').read_bytes())
    if change=='root-keyword':model['additionalProperties']=False
    elif change=='reference-facet':model['$defs']['EnhetOrganisasjonsnummer']['properties']['value']['maxLength']=1
    elif change=='composition-sibling':model['$defs']['RR0002H_M']['enum']=['ignored']
    else:model['@xsdSchemaAttributes']['ElementFormDefault']='Unqualified'
    with pytest.raises(ValueError):resource._constraints(model)
