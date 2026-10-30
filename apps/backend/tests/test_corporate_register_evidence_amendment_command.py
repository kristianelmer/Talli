"""Public business-command wire contract; no persistence or owner proof."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from talli_backend.modules.corporate_governance import public as gov
from test_corporate_register_evidence_amendment import fixture, dumps, follow


def test_frozen_command_and_receipt_vectors_remain_exact():
    corpus = json.loads((Path(__file__).parent / 'fixtures/governance-register-evidence-amendment-goldens.json').read_text())
    receipt = gov.parse_corporate_register_evidence_amendment(corpus['receipt_text'])
    assert gov.serialize_corporate_register_evidence_amendment(receipt) == corpus['receipt_text']
    assert receipt.anchor.anchor_sha256 == corpus['anchor']['anchor_sha256']
    for vector in corpus['vectors']:
        command = gov.parse_corporate_register_evidence_amendment_command(vector['command_text'])
        assert gov.serialize_corporate_register_evidence_amendment_command(command) == vector['command_text']
        assert gov.corporate_register_evidence_amendment_request_digest(command) == vector['request_sha256']


def test_command_wire_matches_frozen_receipt_without_exposing_transport_context():
    _, command, _, receipt = fixture()
    before = gov.serialize_corporate_register_evidence_amendment(receipt)
    encoded = gov.serialize_corporate_register_evidence_amendment_command(command)
    assert encoded == dumps(json.loads(before)['amendment']['command'])
    assert gov.parse_corporate_register_evidence_amendment_command(encoded) == command
    assert gov.corporate_register_evidence_amendment_request_digest(command) == hashlib.sha256(
        dumps(['corporate-register-evidence-amendment-request-v1', json.loads(encoded)]).encode()).hexdigest()
    assert 'idempotency' not in encoded and 'correlation' not in encoded
    assert hashlib.sha256(before.encode()).hexdigest() == 'd60985061b313e6a47c07e05ac44ca1a3509e182cf79220b2a5a39110f4ce88f'


def test_command_wire_retains_exact_prior_head_and_actor_scoped_request_identity():
    _, _, _, first = fixture()
    second = follow(first)
    text = gov.serialize_corporate_register_evidence_amendment_command(second.command)
    assert gov.parse_corporate_register_evidence_amendment_command(text) == second.command
    assert json.loads(text)['expected_head'] == {
        'amendment_id': first.amendment_id.value, 'revision': 1, 'amendment_sha256': first.amendment_sha256}
    assert gov.corporate_register_evidence_amendment_request_digest(second.command) != first.request_sha256


@pytest.mark.parametrize('reason', ['ø 😀 a\u030a\n\t', 'é' * 1000, '\u2003x\u2003', 'control\x01\x1f'])
def test_canonical_command_preserves_unicode_whitespace_and_controls(reason):
    _, command, _, _ = fixture()
    changed = replace(command, reason=reason)
    text = gov.serialize_corporate_register_evidence_amendment_command(changed)
    assert gov.parse_corporate_register_evidence_amendment_command(text).reason == reason
    assert text == dumps(json.loads(text))


@pytest.mark.parametrize('attack', ['extra', 'missing', 'prepared_receipt', 'key', 'correlation', 'bool_year',
    'float_revision', 'exponent_year', 'noncanonical_spacing', 'duplicate', 'bad_actor', 'empty_reason',
    'unicode_blank_reason', 'long_reason', 'null', 'nan', 'wrong_head_revision', 'unknown_source', 'nul', 'surrogate'])
def test_command_parser_rejects_malformed_or_noncanonical_primitives(attack):
    _, command, _, _ = fixture()
    text = gov.serialize_corporate_register_evidence_amendment_command(command)
    value = deepcopy(json.loads(text))
    if attack == 'extra': value['verified'] = True
    elif attack == 'missing': del value['reason']
    elif attack == 'prepared_receipt': value = {'codec': 'corporate-register-evidence-amendment-v1', 'amendment': value}
    elif attack == 'key': value['idempotency_key'] = 'private-transport-key'
    elif attack == 'correlation': value['correlation_id'] = 'mutable-request-trace'
    elif attack == 'bool_year': value['income_year'] = True
    elif attack == 'float_revision': value['replacement']['revision'] = 1.0
    elif attack == 'bad_actor': value['actor_id']['kind'] = 'SYSTEM'
    elif attack == 'empty_reason': value['reason'] = ''
    elif attack == 'unicode_blank_reason': value['reason'] = '\u2003\u0085'
    elif attack == 'long_reason': value['reason'] = 'x' * 1001
    elif attack == 'null': value = None
    elif attack == 'nan': value['replacement']['revision'] = float('nan')
    elif attack == 'wrong_head_revision': value['expected_head'] = {'amendment_id': command.event_id.value, 'revision': False, 'amendment_sha256': 'a' * 64}
    elif attack == 'unknown_source': value['replacement']['verified'] = True
    elif attack == 'nul': value['reason'] = '\x00'
    elif attack == 'surrogate': value['reason'] = '\ud800'
    text = dumps(value)
    if attack == 'exponent_year': text = text.replace('"income_year":2026', '"income_year":2.026e3')
    elif attack == 'noncanonical_spacing': text += ' '
    elif attack == 'duplicate': text = text[:-1] + ',"reason":"duplicate"}'
    with pytest.raises(gov.CorporateRegisterEvidenceAmendmentError):
        gov.parse_corporate_register_evidence_amendment_command(text)
