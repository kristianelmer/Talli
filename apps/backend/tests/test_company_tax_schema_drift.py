"""The release probe must not call a new branch current after a partial read."""
import importlib.util
import json
from pathlib import Path

import pytest

from talli_backend.adapters.company_tax_schemas import _BUNDLE


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
    assert len(source.calls) == len(source.resources)+1 == 11
    assert len(result['files']) == 10 and all(row['matches'] for row in result['files'].values())


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
