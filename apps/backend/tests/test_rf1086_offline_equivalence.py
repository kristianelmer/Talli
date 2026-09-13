"""Pure offline helper outputs captured from pinned 91b before retirement."""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import fields,is_dataclass
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import pytest
from talli_backend.modules.shareholder_register_filing.public import (
    parse_rf1086_offline_simulation_input,simulate_rf1086_offline_submission,
    Rf1086ValidationInput,validate_rf1086_cases,parse_rf1086_case,
    assess_rf1086_readiness,format_rf1086_readiness_report,
    rf1086_code_decisions,rf1086_production_scope_exclusions,rf1086_production_code_blockers,
)
ORACLE=Path(__file__).parent/'fixtures/rf1086_oracle'
SIMULATION=json.loads((ORACLE/'offline-simulation-oracle.json').read_text())
VALIDATION=json.loads((ORACLE/'validation-oracle.json').read_text())
ORIGINAL_CASES={case['name']:case for case in json.loads((ORACLE/'python-oracle.json').read_text())}


def values(value):
    if isinstance(value,datetime):return value.isoformat().replace('+00:00','Z')
    if is_dataclass(value):return {item.name:values(getattr(value,item.name)) for item in fields(value)}
    if isinstance(value,Mapping):return {key:values(item) for key,item in value.items()}
    if isinstance(value,tuple):return [values(item) for item in value]
    return value


@pytest.mark.parametrize('case',SIMULATION,ids=lambda case:case['name'])
def test_offline_planner_matches_original_cli_fields_hashes_and_failures(case):
    instant=datetime(2026,9,9,12,0,0,123456,tzinfo=timezone.utc);count=0
    def clock():
        nonlocal count
        result=instant+timedelta(microseconds=count);count+=1;return result
    try:
        parsed=parse_rf1086_offline_simulation_input(case['input'])
        actual=values(simulate_rf1086_offline_submission(parsed,clock=clock));exit_code=0
    except (KeyError,TypeError,ValueError) as error:
        actual={'status':'failed_blocked','failure_code':'simulation_input_blocked','failure_message':str(error)};exit_code=1
    assert actual==case['output']
    assert exit_code==case['exit_code']


def test_separate_confirmation_times_and_immutable_detached_inputs():
    raw=dict(SIMULATION[0]['input']);raw['underskjema_xml']=dict(raw['underskjema_xml'])
    parsed=parse_rf1086_offline_simulation_input(raw)
    raw['underskjema_xml']['h1']='changed'
    assert parsed.underskjema_xml['h1']=='<sub />'
    with pytest.raises(TypeError):parsed.underskjema_xml['h1']='changed'
    times=iter(datetime(2026,9,9,tzinfo=timezone.utc)+timedelta(seconds=i) for i in range(20))
    result=simulate_rf1086_offline_submission(parsed,clock=lambda:next(times))
    assert result.authority_confirmed_at<result.preview_confirmed_at<result.calls[0].created_at


def test_original_validation_report_values_and_limitations():
    inputs=[]
    for path in VALIDATION['paths']:
        source=ORIGINAL_CASES.get(Path(path).stem)
        if source:
            # Original Pydantic JSON mode can distinguish input mode in a
            # diagnostic, so feed the original serialized file contents.
            inputs.append(Rf1086ValidationInput(path,json.dumps(source['input'])))
        else:inputs.append(Rf1086ValidationInput(path,None,"[Errno 2] No such file or directory: 'missing-case.json'"))
    assert values(validate_rf1086_cases(tuple(inputs)))==VALIDATION['report']


@pytest.mark.parametrize('case',VALIDATION['readiness'],ids=lambda case:Path(case['path']).stem)
def test_original_readiness_text_and_case_specific_code_evidence(case):
    parsed=parse_rf1086_case(ORIGINAL_CASES[Path(case['path']).stem]['input'])
    assert format_rf1086_readiness_report(assess_rf1086_readiness(parsed))==case['text']
    assert [value.code_value for value in rf1086_production_scope_exclusions(parsed)]==case['excludedCodes']
    assert rf1086_production_code_blockers(parsed)==()


def test_original_code_evidence_preserved_without_expanding_live_scope():
    assert values(rf1086_code_decisions())==VALIDATION['codes']
    assert {item.code_value for item in rf1086_production_scope_exclusions()}=={'K','S','U'}
    assert rf1086_production_code_blockers()==()
