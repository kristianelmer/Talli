"""Retained consistency checks neither rerender history nor authenticate its origin."""
from collections.abc import Mapping
from dataclasses import replace
from hashlib import sha256
import json

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.modules.shareholder_register_filing import retained_readiness, retained_source_approval
from test_rf1086_annual_readiness_v2 import inputs_for
from test_rf1086_source_production import manifest_basis
from test_rf1086_source_production_v3 import basis_v3
from test_rf1086_source_readiness_v2 import recommit, record_mapping


def canonical(value):
    def plain(item):
        if isinstance(item, Mapping):
            return {key: plain(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [plain(child) for child in item]
        return item
    return json.dumps(plain(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(text):
    return sha256(text.encode('utf-8')).hexdigest()


def basis(version, *, warning=False):
    if version == 3:
        return basis_v3(annual_changes={'period_lock_ids': ()} if warning else None)
    value = manifest_basis()
    if version == 2:
        inputs = inputs_for(value.source)
        if warning:
            inputs = replace(inputs, period_lock_ids=())
        proof = rf.build_rf1086_annual_readiness(value.source, value.preview, inputs)
        value = replace(value, annual_readiness=proof, acknowledged_warning_codes=proof.required_warning_codes)
    return value


def capture(value, *, raw=True):
    text = rf.serialize_rf1086_source_preview(value.preview)
    return dict(preview_payload_sha256=digest(text), preview_payload_text=text if raw else None)


def binding(proof, version):
    if version == 2:
        from talli_backend.modules.shareholder_register_filing.year_source_storage import _encode
    else:
        from talli_backend.modules.shareholder_register_filing.annual_readiness_storage_v2 import _encode
    number = version - 1
    text = canonical({'codec': f'rf1086-annual-readiness-v{number}', 'proof': _encode(proof)})
    return dict(schemaVersion=f'rf1086-annual-readiness-binding-v{number}',
                proofSha256=proof.proof_sha256, proofTextSha256=digest(text), proofText=text)


def deny_fresh_calls(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError('retained validation invoked a fresh renderer or proof builder')
    for name in (
        'assert_rf1086_source_preview_matches',
        'build_rf1086_source_readiness', 'build_rf1086_source_readiness_v2',
        'assert_rf1086_source_readiness_matches', 'assert_rf1086_source_readiness_matches_v2',
        'build_rf1086_annual_readiness', 'build_rf1086_annual_readiness_v2',
        'assert_rf1086_annual_readiness_matches', 'assert_rf1086_annual_readiness_matches_v2',
        'serialize_rf1086_annual_readiness', 'serialize_rf1086_annual_readiness_v2',
        'build_rf1086_source_approval_manifest', 'build_rf1086_source_approval_manifest_v3',
    ):
        monkeypatch.setattr(rf, name, fail)
    from talli_backend.modules.shareholder_register_filing import source_preview, rendering
    monkeypatch.setattr(source_preview, 'prepare', fail)
    monkeypatch.setattr(source_preview, 'render_rf1086_preview', fail)
    monkeypatch.setattr(rendering, 'render_rf1086_preview', fail)


@pytest.mark.parametrize('version', [1, 2, 3])
@pytest.mark.parametrize('raw', [False, True])
def test_retained_approval_uses_saved_outputs_after_all_fresh_paths_become_unavailable(monkeypatch, version, raw):
    value = basis(version, warning=version != 1)
    approved = (rf.build_rf1086_source_approval_manifest_v3 if version == 3
                else rf.build_rf1086_source_approval_manifest)(value)
    committed = capture(value, raw=raw)
    deny_fresh_calls(monkeypatch)
    actual = retained_source_approval.build_manifest(value, **committed)
    assert actual == approved
    retained_source_approval.assert_matches(approved, value, **committed)
    if version != 1:
        assert retained_readiness.parse_annual_binding(approved.manifest['annualReadiness'],
            value.source, value.preview, **committed) == value.annual_readiness


@pytest.mark.parametrize('version', [1, 2, 3])
def test_retained_reader_can_preserve_consistent_historical_bytes_the_current_renderer_would_reject(monkeypatch, version):
    value = basis(version)
    preview = replace(value.preview, preview_text=value.preview.preview_text + '\nRetained old renderer output.\n',
        hovedskjema_xml=value.preview.hovedskjema_xml + '\n<!-- retained renderer revision -->')
    value = replace(value, preview=preview)
    committed = capture(value)
    if version != 1:
        annual = value.annual_readiness
        source_proof = recommit(replace(annual.source, evidence=replace(annual.source.evidence,
            preview_payload_sha256=committed['preview_payload_sha256'])))
        value = replace(value, annual_readiness=recommit(replace(annual, source=source_proof)))
    with pytest.raises(rf.Rf1086YearSourceError):
        rf.assert_rf1086_source_preview_matches(preview, value.source)
    deny_fresh_calls(monkeypatch)
    actual = retained_source_approval.build_manifest(value, **committed)
    assert actual.manifest['documentHashes'][0]['sha256'] == digest(preview.hovedskjema_xml)
    assert actual.manifest['preview']['reviewTextSha256'] == digest(preview.preview_text)
    # This positive is retained internal consistency only, not an origin attestation.
    retained_source_approval.assert_matches(actual, value, **committed)


@pytest.mark.parametrize('version', [2, 3])
@pytest.mark.parametrize('attack', ['status', 'issues', 'required', 'accepted', 'omissions',
    'input_blocker', 'input_warning', 'input_scope', 'source_status', 'source_issues',
    'source_omissions', 'source_payload', 'source_freshness', 'source_record', 'evidence_record'])
def test_rehashed_annual_proof_must_replay_the_retained_policy_and_bind_saved_source(version, attack):
    value = basis(version, warning=True)
    proof = value.annual_readiness
    if attack == 'status': proof = replace(proof, readiness_status='ready')
    if attack == 'issues': proof = replace(proof, issues=())
    if attack == 'required': proof = replace(proof, required_warning_codes=())
    if attack == 'accepted': proof = replace(proof, accepted_warning_codes=('period_not_locked',))
    if attack == 'omissions': proof = replace(proof, not_evaluated=())
    if attack == 'input_blocker': proof = replace(proof, annual_inputs=replace(proof.annual_inputs, has_unpaid_items=True))
    if attack == 'input_warning': proof = replace(proof, annual_inputs=replace(proof.annual_inputs, bank_balance_confirmed=False))
    if attack == 'input_scope': proof = replace(proof, annual_inputs=replace(proof.annual_inputs, income_year=rf.IncomeYear(2024)))
    source_proof = proof.source
    if attack == 'source_status': source_proof = replace(source_proof, readiness_status='blocked')
    if attack == 'source_issues': source_proof = replace(source_proof, issues=(rf.Rf1086ReadinessIssue('warning', 'invented', 'invented'),))
    if attack == 'source_omissions': source_proof = replace(source_proof, not_evaluated=())
    if attack == 'source_payload': source_proof = replace(source_proof, evidence=replace(source_proof.evidence, preview_payload_sha256='0' * 64))
    if attack == 'source_freshness': source_proof = replace(source_proof, evidence=replace(source_proof.evidence,
        freshness=replace(source_proof.evidence.freshness, documents_sha256='0' * 64)))
    if attack == 'evidence_record': source_proof = replace(source_proof, evidence=record_mapping(source_proof.evidence))
    source_proof = recommit(source_proof)
    if attack == 'source_record': source_proof = record_mapping(source_proof)
    proof = recommit(replace(proof, source=source_proof))
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        retained_readiness.parse_annual_binding(binding(proof, version), value.source, value.preview, **capture(value))


@pytest.mark.parametrize('version', [2, 3])
@pytest.mark.parametrize('attack', ['codec', 'record_tag', 'duplicate_key', 'noncanonical', 'extra', 'bool_year'])
def test_retained_annual_codec_rejects_rehashed_shape_and_encoding_substitutions(version, attack):
    value = basis(version)
    encoded = binding(value.annual_readiness, version)
    raw = json.loads(encoded['proofText'])
    if attack == 'codec': raw['codec'] = 'rf1086-annual-readiness-v99'
    if attack == 'record_tag': raw['proof']['record'] = 'Rf1086SourcePreview'
    if attack == 'extra': raw['verified'] = True
    if attack == 'bool_year': raw['proof']['fields']['annual_inputs']['fields']['income_year']['fields']['value'] = True
    text = canonical(raw)
    if attack == 'duplicate_key': text = '{"codec":"ignored",' + text[1:]
    if attack == 'noncanonical': text += '\n'
    encoded.update(proofText=text, proofTextSha256=digest(text))
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        retained_readiness.parse_annual_binding(encoded, value.source, value.preview, **capture(value))


@pytest.mark.parametrize('version', [1, 2, 3])
@pytest.mark.parametrize('attack', ['payload_digest', 'other_payload', 'wrong_source', 'wrong_year', 'unknown_profile'])
def test_retained_preview_requires_exact_scope_and_saved_payload_commitment(version, attack):
    value = basis(version)
    committed = capture(value)
    if attack == 'payload_digest': committed['preview_payload_sha256'] = '0' * 64
    if attack == 'other_payload':
        committed['preview_payload_text'] = rf.serialize_rf1086_source_preview(replace(value.preview, preview_text='other'))
        committed['preview_payload_sha256'] = digest(committed['preview_payload_text'])
    if attack == 'wrong_source': value = replace(value, preview=replace(value.preview, source_sha256='0' * 64))
    if attack == 'wrong_year': value = replace(value, preview=replace(value.preview, income_year=rf.IncomeYear(2024)))
    if attack == 'unknown_profile': value = replace(value, preview=replace(value.preview, rendering_profile='unknown'))
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        retained_source_approval.build_manifest(value, **committed)


@pytest.mark.parametrize('version', [2, 3])
def test_annual_versions_cannot_be_relabelled_across_source_codecs(version):
    value = basis(version)
    other = basis(5 - version)
    changed = replace(value, annual_readiness=other.annual_readiness)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        retained_source_approval.build_manifest(changed, **capture(value))


@pytest.mark.parametrize('version', [1, 2, 3])
@pytest.mark.parametrize('attack', ['missing', 'extra', 'schema', 'documents', 'xml', 'order'])
def test_assertion_rejects_rehashed_incomplete_manifest_or_changed_document_result(version, attack):
    value = basis(version)
    committed = capture(value)
    approved = retained_source_approval.build_manifest(value, **committed)
    raw = json.loads(canonical(dict(approved.manifest)))
    if attack == 'missing': del raw['freshness']
    if attack == 'extra': raw['trusted'] = True
    if attack == 'schema': raw['schemaVersion'] = 'production-source-approval-v99'
    if attack == 'documents': raw['documentHashes'][0]['sha256'] = '0' * 64
    changes = dict(manifest=raw, manifest_sha256=digest(canonical(raw)))
    if attack == 'xml': changes['underskjema_xml'] = {'other': '<other/>'}
    if attack == 'order': changes['document_order'] = ()
    with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'):
        retained_source_approval.assert_matches(replace(approved, **changes), value, **committed)
