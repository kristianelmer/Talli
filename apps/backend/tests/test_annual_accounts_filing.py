"""Frozen predecessor conformance through the owned public contract."""
from collections.abc import Mapping
from dataclasses import asdict, FrozenInstanceError
import json
import math
from pathlib import Path

import pytest

from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsCandidate, AnnualAccountsCorporateReadiness, AnnualAccountsReadinessIssue,
    AnnualAccountsRenderInput, AnnualAccountsSource, assess_annual_accounts_readiness,
    build_annual_accounts, render_annual_accounts,
)

ROOT = Path(__file__).resolve().parents[3]
CAPTURE = json.loads((ROOT / 'architecture/evidence/issues/153/characterization/legacy-pure-characterization.json').read_text())


def source(value):
    return AnnualAccountsSource(value['incomeYear'], value['annualData'], tuple(value['ledgerEntries']))


def candidate(value):
    return AnnualAccountsCandidate(value['schemaType'], value['hovedskjemaDataFormatId'],
        value['hovedskjemaDataFormatVersion'], value['selskapsregnskapDataFormatId'],
        value['selskapsregnskapDataFormatVersion'], value.get('notes', {}),
        tuple(value['fields']), tuple(value['feedback']))


def payload(value):
    return {'schemaType': value.schema_type, 'hovedskjemaDataFormatId': value.main_form_format_id,
        'hovedskjemaDataFormatVersion': value.main_form_format_version, 'selskapsregnskapDataFormatId': value.accounts_format_id,
        'selskapsregnskapDataFormatVersion': value.accounts_format_version, 'notes': value.notes,
        'fields': value.fields, 'feedback': value.feedback}


def capture(fn):
    try:
        result = fn()
    except ValueError as error:
        return {'error': {'name': 'Error', 'message': str(error)}}
    special = []

    def wire(value, path=()):
        if isinstance(value, float) and (not math.isfinite(value) or value == 0 and math.copysign(1, value) < 0):
            kind = 'NaN' if math.isnan(value) else '-Infinity' if value == -math.inf else 'Infinity' if value == math.inf else '-0'
            special.append({'path': list(path), 'kind': kind})
            return None if not math.isfinite(value) else 0
        if isinstance(value, Mapping):
            return {key: wire(item, (*path, key)) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [wire(item, (*path, str(i))) for i, item in enumerate(value)]
        return value

    output = {'value': wire(result)}
    if special:
        output['numericSpecials'] = special
    return output


@pytest.mark.parametrize('case', CAPTURE['payloadCases'], ids=lambda case: case['id'])
def test_payload_matches_original_order_values_feedback_and_numeric_semantics(case):
    assert capture(lambda: payload(build_annual_accounts(source(case['input'])))) == case['output']


@pytest.mark.parametrize('case', CAPTURE['xmlCases'], ids=lambda case: case['id'])
def test_xml_matches_original_bytes_or_ordered_rejection(case):
    value = case['input']
    request = AnnualAccountsRenderInput(candidate(value['payload']), value['companyOrgNumber'],
        value['companyName'], value['contactEmail'], value['approvalDate'], value['confirmingRepresentative'])

    def render():
        result = render_annual_accounts(request)
        return {'mainFormXml': result.main_form_xml, 'companyAccountsXml': result.company_accounts_xml}

    assert capture(render) == case['output']


@pytest.mark.parametrize('case', CAPTURE['readinessCases'], ids=lambda case: case['id'])
def test_accounts_readiness_preserves_corporate_blocks_and_order(case):
    value = case['input']
    corporate = value.get('corporateDocuments')
    if corporate is not None:
        corporate = AnnualAccountsCorporateReadiness(corporate['enabled'], tuple(
            AnnualAccountsReadinessIssue('block', item['code'], item['message'], 'corporate_documents')
            for item in corporate['readiness']['blockers']))
    assert capture(lambda: [asdict(issue) for issue in assess_annual_accounts_readiness(
        source(value), company_id=value['company']['id'], corporate=corporate)]) == case['output']


def test_snapshots_do_not_alias_caller_data_or_expose_mutable_results():
    value = json.loads(json.dumps(CAPTURE['payloadCases'][0]['input']))
    snapshot = source(value)
    first = build_annual_accounts(snapshot)
    value['annualData']['confirmations'].append('annual_accounts_audit_required')
    value['ledgerEntries'][0]['lines'][0]['debit'] = 1
    assert capture(lambda: payload(build_annual_accounts(snapshot))) == capture(lambda: payload(first))
    with pytest.raises(TypeError):
        snapshot.ledger_entries[0]['lines'][0]['debit'] = 1
    with pytest.raises(TypeError):
        first.fields[0]['value'] = 2024
    with pytest.raises(FrozenInstanceError):
        first.schema_type = 'changed'


@pytest.mark.parametrize('location', ['annual', 'ledger'])
def test_deep_ignored_json_metadata_preserves_original_payload(location):
    value = json.loads(json.dumps(CAPTURE['payloadCases'][0]['input']))
    nested = {'synthetic': True}
    for _ in range(600):
        nested = [nested]
    target = value['annualData'] if location == 'annual' else value['ledgerEntries'][0]
    target['ignored'] = nested
    assert capture(lambda: payload(build_annual_accounts(source(value)))) == CAPTURE['payloadCases'][0]['output']


@pytest.mark.parametrize('sign', [-1, 1])
def test_unbounded_json_integer_amount_retains_signed_binary64_overflow(sign):
    value = json.loads(json.dumps(CAPTURE['payloadCases'][0]['input']))
    value['ledgerEntries'][0]['lines'] = [{'account': '1920', 'debit': sign * 10 ** 400, 'credit': 0}]
    result = build_annual_accounts(source(value))
    amounts = {field['tag']: field['value'] for field in result.fields}
    assert amounts['sumBankinnskuddKontanter/aarets'] == sign * math.inf
    assert amounts['sumEiendeler/aarets'] == sign * math.inf
