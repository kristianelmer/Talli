"""Actual HTTP validation must positively prove a recognized result before lock."""
import asyncio
import httpx
import pytest
from test_authority_filing_transports import queue, annual_instance, ORG, XML, ALTINN_TOKEN
from talli_backend.adapters.annual_accounts_authority import AnnualAccountsTransport
from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsAuthorityError, prepare_annual_accounts_for_signing


@pytest.mark.parametrize('body', [
    '<html>upstream failure</html>', '{}', 'null', 'true', '0',
    '{"validationIssues":"not-an-array"}', '[null]', '[{}]',
    '[{"severity":0}]', '[{"severity":true}]', '[{"severity":"unknown"}]',
])
def test_malformed_validation_never_locks(body):
    transport, requests, _ = queue(annual_instance(), httpx.Response(201), httpx.Response(201), httpx.Response(200, text=body))
    with pytest.raises(AnnualAccountsAuthorityError) as failure:
        asyncio.run(prepare_annual_accounts_for_signing(AnnualAccountsTransport(ALTINN_TOKEN, transport=transport),
            company_org_number=ORG, main_form_xml=XML, company_accounts_xml=XML))
    assert failure.value.code == 'ANNUAL_ACCOUNTS_VALIDATION_RESPONSE_INVALID'
    assert not any(r.url.path.endswith('/process/next') for r in requests)


@pytest.mark.parametrize('severity', [1, 'Error', 'error'])
def test_numeric_and_named_validation_errors_block(severity):
    transport, requests, _ = queue(annual_instance(), httpx.Response(201), httpx.Response(201), [{'severity': severity, 'code': 'BLOCK'}])
    with pytest.raises(AnnualAccountsAuthorityError) as failure:
        asyncio.run(prepare_annual_accounts_for_signing(AnnualAccountsTransport(ALTINN_TOKEN, transport=transport),
            company_org_number=ORG, main_form_xml=XML, company_accounts_xml=XML))
    assert failure.value.code == 'ANNUAL_ACCOUNTS_VALIDATION_FAILED'
    assert failure.value.validation_codes == ['BLOCK']
    assert not any(r.url.path.endswith('/process/next') for r in requests)


@pytest.mark.parametrize('body', [[], {'validationIssues': []}, *[[{'severity': s, 'code': 'SOFT'}] for s in [2, 3, 4, 5, 'Warning', 'Informational', 'Fixed', 'Success']]])
def test_valid_empty_and_recognized_soft_validation_can_lock(body):
    transport, requests, _ = queue(annual_instance(), httpx.Response(201), httpx.Response(201), body,
        {'currentTask': {'altinnTaskType': 'signing'}}, annual_instance('signing'))
    result = asyncio.run(prepare_annual_accounts_for_signing(AnnualAccountsTransport(ALTINN_TOKEN, transport=transport),
        company_org_number=ORG, main_form_xml=XML, company_accounts_xml=XML))
    assert result['validation']['hasErrors'] is False
    assert sum(r.url.path.endswith('/process/next') for r in requests) == 1


@pytest.mark.parametrize('body', [{}, {'currentTask': {'altinnTaskType': 'data'}}, {'currentTask': None}])
def test_unknown_lock_response_never_claims_signing_handoff(body):
    transport, requests, _ = queue(annual_instance(), httpx.Response(201), httpx.Response(201), [], body)
    with pytest.raises(AnnualAccountsAuthorityError) as failure:
        asyncio.run(prepare_annual_accounts_for_signing(AnnualAccountsTransport(ALTINN_TOKEN, transport=transport),
            company_org_number=ORG, main_form_xml=XML, company_accounts_xml=XML))
    assert failure.value.code == 'ANNUAL_ACCOUNTS_SIGNING_STATE_UNCONFIRMED'
    assert len(requests) == 5


def test_handoff_requires_observed_signing_task():
    transport, _, _ = queue(annual_instance('data'))
    from test_authority_filing_transports import ID
    with pytest.raises(AnnualAccountsAuthorityError) as failure:
        asyncio.run(AnnualAccountsTransport(ALTINN_TOKEN, transport=transport).get_signing_handoff(instance_id=ID))
    assert failure.value.code == 'ANNUAL_ACCOUNTS_SIGNING_STATE_UNCONFIRMED'
