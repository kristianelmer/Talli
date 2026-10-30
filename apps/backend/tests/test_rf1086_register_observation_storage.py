"""Closed observation codec preserves exact independently verified register facts."""
from dataclasses import replace
import json
import pytest
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_register_observation import prepare, basis

@pytest.mark.parametrize('kind',['cash_issue','cash_nominal_increase','loss_covering_reduction'])
def test_observation_codec_preserves_original_facts(kind):
    c,ctx=basis(kind);snapshot=prepare(c,ctx)
    encoded=rf.serialize_rf1086_register_observation(snapshot)
    assert rf.parse_rf1086_register_observation(encoded)==snapshot
    assert rf.serialize_rf1086_register_observation(rf.parse_rf1086_register_observation(encoded))==encoded

@pytest.mark.parametrize('mutation',['type','hash','field','codec','duplicate','nan','malformed_decimal'])
def test_observation_storage_rejects_corrupt_or_executable_records(mutation):
    encoded=rf.serialize_rf1086_register_observation(prepare());raw=json.loads(encoded)
    if mutation=='type':raw['snapshot']['record']='os.system'
    if mutation=='hash':raw['snapshot']['fields']['fact_sha256']='0'*64
    if mutation=='field':del raw['snapshot']['fields']['version']
    if mutation=='codec':raw['codec']='rf1086-year-source-v1'
    if mutation=='nan':raw['snapshot']['fields']['command']['fields']['before']['fields']['share_capital']={'decimal':'NaN'}
    if mutation=='malformed_decimal':raw['snapshot']['fields']['command']['fields']['before']['fields']['share_capital']={'decimal':'invalid decimal'}
    encoded=json.dumps(raw)
    if mutation=='duplicate':encoded=encoded.replace('"version": 1','"version": 1, "version": 2')
    with pytest.raises(rf.Rf1086RegisterObservationError):rf.parse_rf1086_register_observation(encoded)
