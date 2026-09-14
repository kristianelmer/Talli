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


@pytest.mark.parametrize('case', TRACES['cases'], ids=lambda case: case['id'])
def test_owned_rehearsal_preserves_original_effect_order_and_durable_checkpoints(case):
    assert trace(annual_accounts_test, case['id'], relocated=True) == case['trace']


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
