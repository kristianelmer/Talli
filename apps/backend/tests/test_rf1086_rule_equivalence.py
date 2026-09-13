"""Fixed-input oracle captured at 91b before either original owner was retired."""
from dataclasses import fields, is_dataclass
from collections.abc import Mapping
import json
from pathlib import Path
import pytest
from talli_backend.modules.shareholder_register_filing.public import (
    parse_rf1086_case, render_rf1086_preview, render_no_activity_rf1086_preview, rf1086_xml_schema,
)
ORACLE = Path(__file__).parent / 'fixtures/rf1086_oracle'
def values(value):
    if is_dataclass(value): return {item.name:values(getattr(value,item.name)) for item in fields(value)}
    if isinstance(value,Mapping): return {key:values(item) for key,item in value.items()}
    if isinstance(value,tuple): return [values(item) for item in value]
    return value

def render_values(result):
    output = values(result)
    output['hovedskjemaXml'] = output.pop('hovedskjema_xml')
    output['underskjemaXml'] = output.pop('underskjema_xml')
    if output['hovedskjemaXml'] is None:
        output.pop('hovedskjemaXml'); output.pop('underskjemaXml')
    return output

@pytest.mark.parametrize('case',json.loads((ORACLE/'python-oracle.json').read_text()),ids=lambda case:case['name'])
def test_original_python_case_output(case):
    if 'error' in case:
        with pytest.raises(ValueError) as failure: parse_rf1086_case(case['input'])
        assert str(failure.value) == case['error']['message']
        return
    parsed = parse_rf1086_case(case['input'])
    assert render_values(render_rf1086_preview(parsed)) == case['output']

@pytest.mark.parametrize('case',json.loads((ORACLE/'web-oracle.json').read_text()),ids=lambda case:case['name'])
def test_original_deployed_renderer_output(case):
    assert render_values(render_no_activity_rf1086_preview(case['input'])) == case['output']

def test_civil_timestamp_and_arbitrary_holder_id_remain_values():
    source = next(case for case in json.loads((ORACLE/'python-oracle.json').read_text()) if case.get('normalizedInput',{}).get('events') and case['normalizedInput']['events'][0]['type']=='formation')
    parsed = parse_rf1086_case(source['input'])
    assert parsed.events[0].timestamp.tzinfo is None
    assert parsed.shareholders[0].id == source['input']['shareholders'][0]['id']
    with pytest.raises((AttributeError,TypeError)): parsed.shareholders += parsed.shareholders
    assert not hasattr(parsed,'__dict__')

@pytest.mark.parametrize('document,name',[('hovedskjema','aksjonaerregisteroppgaveHovedskjema.xsd'),('underskjema','aksjonaerregisteroppgaveUnderskjema.xsd')])
def test_packaged_schema_keeps_original_bytes(document,name):
    import hashlib
    manifest = json.loads((ORACLE/'manifest.json').read_text())
    assert hashlib.sha256(rf1086_xml_schema(document)).hexdigest() == manifest['files']['docs/filing/'+name]


def test_opening_builder_preserves_source_ids_and_default_address():
    from talli_backend.modules.shareholder_register_filing.public import (
        Rf1086CompanyFacts,Rf1086OpeningFacts,Rf1086OpeningShareholderFact,Rf1086ShareholderKind,
        OpeningSnapshotId,build_no_activity_rf1086_case,
    )
    from talli_backend.shared.kernel import CompanyId,IncomeYear
    company_id=CompanyId('10000000-0000-4000-8000-000000000001')
    setup_id=OpeningSnapshotId('40000000-0000-4000-8000-000000000004')
    company=Rf1086CompanyFacts(company_id,'923456789','Holding AS',None,'0123','')
    holder=Rf1086OpeningShareholderFact('original-holder',Rf1086ShareholderKind.NORWEGIAN_PERSON,'Eier','12345678901',None,100)
    opening=Rf1086OpeningFacts(company_id,setup_id,IncomeYear(2025),30000,100,300,(holder,))
    case=build_no_activity_rf1086_case(company=company,opening=opening)
    assert case.case_id=='persisted-923456789-2025-'+str(setup_id)
    assert case.company.address=='Ukjent adresse' and case.company.city=='Ukjent'
    assert case.shareholders[0].id=='original-holder' and case.events==()
    assert case.share_snapshot.previous_share_capital==case.share_snapshot.current_share_capital==30000
    assert case.share_snapshot.previous_paid_in_premium==case.share_snapshot.current_paid_in_premium==0
