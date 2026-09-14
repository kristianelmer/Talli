"""Retained statutory hashes and the tax CLI's in-process public boundary."""
import hashlib
import json
import math
from pathlib import Path
import subprocess

import pytest

from talli_backend.authority_tools._filing import payload

ROOT = Path(__file__).resolve().parents[3]


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def test_tax_cli_uses_owned_contract_without_a_node_child_and_preserves_statutory_hashes(monkeypatch):
    def forbidden_child(*args, **kwargs):
        pytest.fail('Company Tax invoked a payload subprocess')
    monkeypatch.setattr(subprocess, 'run', forbidden_child)
    case = json.loads((ROOT / 'tests/fixtures/authority/company-tax-no-activity-2025.json').read_text())
    input = {'companyOrgNumber': case['company']['orgNumber'], 'companyPartyNumber': '1234567',
             'incomeYear': case['company']['incomeYear'], 'annualData': case['annualData'],
             'ledgerEntries': case['ledgerEntries'], 'holdingActions': case['holdingActions']}
    documents = payload('company_tax', input)
    assert digest(documents['skattemeldingXml']) == '42f1424f872f108daecb5d0429e473f1bebaebc3a407990f04dcff6fd1fd7a44'
    assert digest(documents['naeringsspesifikasjonXml']) == 'ab43d1a3120d6cb50c09f1a88ef211a49b4b3e31233342179a76871badf52599'
    envelope = {**documents, 'companyOrgNumber': input['companyOrgNumber'], 'incomeYear': input['incomeYear'], 'createdBy': 'Talli'}
    assert digest(payload('company_tax_validation_envelope', envelope)['envelopeXml']) == '67191b4b3574401afeacbf9ce02b20ce7600d88255f2acd63cb65a4a5f8be113'
    assert digest(payload('company_tax_envelope', {**envelope, 'currentDocumentReference': 'SKI:755:1'})['envelopeXml']) == '8beaf7dd98950f70b7c2a6f0b39fd5726d04291a2a6905091ca83c1e594743de'
    assert payload('company_tax_validation_summary', {'resultXml': '<r><resultatAvValidering>validertMedFeil</resultatAvValidering><avvikstype>B</avvikstype><avvikstype>A</avvikstype><avvikstype>B</avvikstype><veiledningstype>C</veiledningstype><aarsakTilValidertMedFeil>UgyldigPartsnummer</aarsakTilValidertMedFeil><calculatedDocument>private</calculatedDocument></r>'}) == {
        'result': 'validertMedFeil', 'deviationCodes': ['A', 'B'], 'guidanceCodes': ['C'], 'failureReasons': ['UgyldigPartsnummer']}
    with pytest.raises(ValueError, match='^Local authority payload generation failed.$'):
        payload('company_tax', {**input, 'annualData': None})


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf])
def test_tax_cli_preserves_json_boundary_even_for_ignored_nonstandard_constants(value):
    with pytest.raises(ValueError, match='^Local authority payload generation failed.$'):
        payload('company_tax_validation_summary', {'resultXml': '<r/>', 'ignored': value})


def test_tax_cli_retains_utf8_output_limit_and_lone_surrogate_summary(monkeypatch):
    from talli_backend.authority_tools import _filing, company_tax_payload

    # The old child emits compact JSON.stringify UTF-8, including escaped lone
    # surrogates. ASCII escaping or extra separator spaces changes this limit.
    result = {'x': '\u00e6' * 100 + '\ud83d'}
    monkeypatch.setattr(company_tax_payload, 'generate', lambda *_: result)
    # Eight JSON punctuation/key bytes, 200 UTF-8 bytes and six escape bytes.
    monkeypatch.setattr(_filing, 'MAX_RESPONSE_BYTES', 214)
    assert payload('company_tax', {}) == result
    monkeypatch.setattr(_filing, 'MAX_RESPONSE_BYTES', 213)
    with pytest.raises(ValueError, match='^Local authority payload generation failed.$'):
        payload('company_tax', {})


@pytest.mark.parametrize('operation', ['company_tax_envelope', 'company_tax_validation_envelope'])
def test_tax_cli_distinguishes_omitted_and_explicit_null_document_reference(operation):
    value = {'skattemeldingXml': '<tax/>', 'naeringsspesifikasjonXml': '<business/>',
             'companyOrgNumber': '923609016', 'incomeYear': 2025, 'createdBy': 'Talli'}
    assert '<dokumentreferanseTilGjeldendeDokument>' not in payload(operation, value)['envelopeXml']
    for invalid in (None, '', ' '):
        with pytest.raises(ValueError, match='^Local authority payload generation failed.$'):
            payload(operation, {**value, 'currentDocumentReference': invalid})
    assert '<dokumentidentifikator>SKI:755:1</dokumentidentifikator>' in payload(
        operation, {**value, 'currentDocumentReference': 'SKI:755:1'})['envelopeXml']


def test_tax_cli_integral_json_float_year_keeps_statutory_xml_bytes():
    case = json.loads((ROOT / 'tests/fixtures/authority/company-tax-no-activity-2025.json').read_text())
    value = {'companyOrgNumber': case['company']['orgNumber'], 'companyPartyNumber': '1234567',
             'incomeYear': 2025.0, 'annualData': case['annualData'],
             'ledgerEntries': case['ledgerEntries'], 'holdingActions': case['holdingActions']}
    documents = payload('company_tax', value)
    assert digest(documents['skattemeldingXml']) == '42f1424f872f108daecb5d0429e473f1bebaebc3a407990f04dcff6fd1fd7a44'
    assert digest(documents['naeringsspesifikasjonXml']) == 'ab43d1a3120d6cb50c09f1a88ef211a49b4b3e31233342179a76871badf52599'
