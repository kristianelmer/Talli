"""The release probe must not call a new branch current after a partial read."""
import importlib.util
import json
from pathlib import Path

import pytest

from talli_backend.adapters.company_tax_schemas import _BUNDLE
from talli_backend.adapters import company_tax_response_schemas as response_resource


spec = importlib.util.spec_from_file_location('tax_schema_drift',
    Path(__file__).resolve().parents[3]/'scripts/check_company_tax_schema_drift.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
COMMIT = 'f'*40


class Source:
    def __init__(self):
        self.calls = []
        self.head = {'ref':'refs/heads/master','object':{'type':'commit','sha':COMMIT}}
        self.manifest = json.loads((_BUNDLE/'manifest.json').read_bytes())
        self.resources = {probe.RAW+COMMIT+'/'+entry['sourcePath']:(_BUNDLE/name).read_bytes()
            for name,entry in self.manifest['files'].items()}
        self.response_manifest = json.loads((response_resource._BUNDLE/'manifest.json').read_bytes())
        self.resources.update({probe.RAW+COMMIT+'/'+entry['sourcePath']:(response_resource._BUNDLE/name).read_bytes()
            for name,entry in self.response_manifest['files'].items()})

    def fetch(self,url):
        self.calls.append(url)
        if url == probe.HEAD:
            return json.dumps(self.head).encode()
        return self.resources[url]


def test_complete_matching_resources_are_current_even_if_other_years_moved():
    source = Source()
    result = probe.verify_current(source.fetch)
    assert result['status'] == 'current' and result['completeEnumeration'] is True
    assert result['observedSourceCommit'] == COMMIT
    assert result['observedSourceCommit'] != result['approvedSourceCommit']
    assert len(source.calls) == len(source.resources)+1 == 12
    assert len(result['files']) == 10 and all(row['matches'] for row in result['files'].values())
    assert result['schema'] == 'company-tax-schema-drift-v2'
    assert len(result['validationResponse']['files']) == 2
    assert all(row['matches'] for row in result['validationResponse']['files'].values())


def test_one_changed_code_list_is_drift_not_a_current_or_incomplete_verdict():
    source = Source()
    key = next(url for url in source.resources if url.endswith('2025_resultatregnskapOgBalanse.xml'))
    source.resources[key] += b'\n'
    result = probe.verify_current(source.fetch)
    assert result['status'] == 'drift' and result['completeEnumeration'] is True
    assert [name for name,row in result['files'].items() if not row['matches']] == ['2025_resultatregnskapOgBalanse.xml']


@pytest.mark.parametrize('head', [None, [], {}, {'ref':'other','object':{'type':'commit','sha':COMMIT}},
    {'ref':'refs/heads/master','object':{'type':'tag','sha':COMMIT}},
    {'ref':'refs/heads/master','object':{'type':'commit','sha':'https://example.test/other'}},
    {'ref':'refs/heads/master','object':{'type':'commit','sha':'../private'}}])
def test_malformed_source_reference_cannot_select_a_new_url(head):
    source = Source();source.head = head
    with pytest.raises(ValueError): probe.verify_current(source.fetch)
    assert source.calls == [probe.HEAD]


def test_partial_or_oversized_resource_read_cannot_produce_a_current_verdict():
    source = Source()
    key = next(iter(source.resources))
    source.resources[key] = b'x'*(probe.MAX_RESPONSE+1)
    with pytest.raises(ValueError): probe.verify_current(source.fetch)
    del source.resources[key]
    with pytest.raises(KeyError): probe.verify_current(source.fetch)


def test_response_schema_drift_is_not_hidden_by_current_delivery_resources():
    source = Source()
    key = next(url for url in source.resources if url.endswith('skattemeldingognaeringsspesifikasjonresponse_v2.xsd'))
    source.resources[key] += b'\n'
    result = probe.verify_current(source.fetch)
    assert result['status'] == 'drift' and result['completeEnumeration'] is True
    assert all(row['matches'] for row in result['files'].values())
    assert not result['validationResponse']['files']['skattemeldingognaeringsspesifikasjonresponse_v2.xsd']['matches']
    del source.resources[key]
    with pytest.raises(KeyError):probe.verify_current(source.fetch)


def test_unavailable_local_response_pin_prevents_every_network_read(tmp_path,monkeypatch):
    source = Source()
    monkeypatch.setattr(response_resource,'_BUNDLE',tmp_path/'missing-bundle')
    with pytest.raises(Exception):probe.verify_current(source.fetch)
    assert source.calls == []
