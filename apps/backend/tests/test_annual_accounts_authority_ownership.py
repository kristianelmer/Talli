"""Accounts authority migration preserves the frozen CLI payload boundary."""
import asyncio
import json
from pathlib import Path

import pytest

from talli_backend.authority_tools._filing import payload
from talli_backend.modules.annual_accounts_filing.public import prepare_annual_accounts_for_signing
from talli_backend.authority_tools import annual_accounts_test
from annual_accounts_rehearsal_trace import trace

ROOT = Path(__file__).resolve().parents[3]
CAPTURE = json.loads((ROOT / 'architecture/evidence/issues/153/authority-ownership/legacy-annual-payload-bridge.json').read_text())
TRACES = json.loads((ROOT / 'architecture/evidence/issues/153/authority-ownership/legacy-rehearsal-traces.json').read_text())
BOUNDARY_CASES = json.loads((ROOT / 'architecture/evidence/issues/153/authority-review-fixes/authority-spec-actual-bridge-results-50bfe67a.json').read_text())


@pytest.mark.parametrize('case', BOUNDARY_CASES, ids=lambda case: f"{case['field']}={case['value']!r}")
def test_reviewed_json_shapes_preserve_actual_predecessor_subprocess_boundary(case):
    try:
        result = {'value': payload('annual_accounts', case['input'])}
    except ValueError as error:
        result = {'error': type(error).__name__, 'message': str(error)}
    assert result == case['old']


def without_operation_journal(value):
    if isinstance(value, list):
        return [without_operation_journal(item) for item in value]
    if isinstance(value, dict):
        return {key: without_operation_journal(item) for key, item in value.items() if key != 'operationJournalVersion'}
    return value


@pytest.mark.parametrize('case', TRACES['cases'], ids=lambda case: case['id'])
def test_owned_rehearsal_preserves_original_trace_except_required_ambiguity_guard(case):
    actual = trace(annual_accounts_test, case['id'], relocated=True)
    # Same provider calls, payloads, reads and ordering. The explicit #132 safety
    # correction adds journal saves and blocks an ambiguous create/lock result.
    effects = lambda value: [row for row in value['events'] if row['operation'] not in ('save_evidence', 'connect')]
    assert effects(actual) == effects(case['trace'])
    if case['id'] in ('create_instance', 'lock_for_signing'):
        pending = actual['checkpoints'][-1]
        assert pending['status'] == 'reconciliation_required'
        assert pending['pendingAuthorityOperation']['operation'] == case['id']
        assert pending['pendingAuthorityOperation']['failure']['code'] == 'ANNUAL_ACCOUNTS_NETWORK_ERROR'
        assert pending['error']['code'] == 'ANNUAL_ACCOUNTS_RECONCILIATION_REQUIRED'
        assert pending['error']['retryable'] is False
        assert pending['instance'] == case['trace']['checkpoints'][-1]['instance']
        assert actual['output'] == {'error': {'type': 'AnnualAccountsAuthorityError',
            'message': 'An earlier authority operation may have completed. Reconcile the saved evidence before retrying.'}}
        return
    normalized = without_operation_journal(actual)
    normalized['checkpoints'] = [row for row in normalized['checkpoints'] if 'pendingAuthorityOperation' not in row]
    normalized['events'] = [row for row in normalized['events']
        if not (row['operation'] == 'save_evidence' and 'pendingAuthorityOperation' in row['input'])]
    assert normalized == case['trace']


@pytest.mark.parametrize('case', CAPTURE['cases'], ids=lambda case: case['id'])
def test_python_cli_payload_matches_frozen_node_result_or_failure(case):
    try:
        result = {'value': payload('annual_accounts', case['input'])}
    except ValueError as error:
        result = {'error': str(error)}
    assert result == case['output']


@pytest.mark.parametrize('operation', ['../../evil.js', 'exec', 'https://evil.invalid/'])
def test_fixed_payload_dispatch_rejects_arbitrary_targets(operation):
    with pytest.raises(ValueError, match='^Unknown fixed payload operation.$'):
        payload(operation, {'privateKey': 'private-input-marker'})


def test_public_prepare_copies_provider_owned_result_and_nested_lists():
    class Authority:
        def __init__(self):
            self.created = {'id': 'instance', 'dataIds': {'mainForm': 'main', 'companyAccounts': 'accounts'}}
            self.validation = {'hasErrors': False, 'issues': [{'code': 'warning', 'severity': 'Warning'}]}
        async def create_instance(self, **_): return self.created
        async def upload_main_form(self, **_): return {}
        async def upload_company_accounts(self, **_): return {}
        async def validate_instance(self, **_): return self.validation
        async def lock_for_signing(self, **_): return {}
        async def get_signing_handoff(self, **_): return {'signed': False, 'submitted': False}

    client = Authority()
    result = asyncio.run(prepare_annual_accounts_for_signing(client,
        company_org_number='310279617', main_form_xml='<main/>', company_accounts_xml='<accounts/>'))
    client.created['dataIds']['mainForm'] = 'changed'
    client.validation['issues'][0]['code'] = 'changed'
    assert result['dataIds']['mainForm'] == 'main'
    assert result['validation']['issues'][0]['code'] == 'warning'
    with pytest.raises(TypeError):
        result['validation']['issues'][0]['code'] = 'accepted'
