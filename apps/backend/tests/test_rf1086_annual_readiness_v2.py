"""Versioned annual proof storage preserves policy without enabling submission."""
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import json
from uuid import UUID

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_source_preview import preview_source
from test_rf1086_source_readiness_v2 import KINDS, recommit, source_and_preview
from test_rf1086_year_source import basis as old_basis, prepare as old_prepare


def uid(number):
    return str(UUID(int=number))


def inputs_for(source):
    return rf.Rf1086AnnualReadinessInputs(source.company_id, source.income_year,
        (uid(9001),), (uid(9001),), (uid(9002),), 3, 0, 1, uid(9003),
        True, False, True, (), {name: 'a' * 64 for name in ('opening', 'ledger', 'banking', 'interview', 'documents')})


def annual(kind='cash_issue', *, amendments=2, changes=None):
    source, preview = source_and_preview(kind, amendments=amendments)
    inputs = replace(inputs_for(source), **(changes or {}))
    return source, preview, inputs, rf.build_rf1086_annual_readiness_v2(source, preview, inputs)


def binding(proof, source, preview):
    text = rf.serialize_rf1086_annual_readiness_v2(proof, source, preview)
    return dict(schemaVersion='rf1086-annual-readiness-binding-v2', proofSha256=proof.proof_sha256,
        proofTextSha256=sha256(text.encode()).hexdigest(), proofText=text)


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('amendments', [0, 1, 2])
def test_complete_v2_annual_proof_roundtrips_with_explicit_source_version(kind, amendments):
    source, preview, inputs, proof = annual(kind, amendments=amendments)
    assert type(proof) is rf.Rf1086AnnualReadinessProofV2
    assert proof.schema_version == 'rf1086-annual-readiness-v2'
    assert proof.source == rf.build_rf1086_source_readiness_v2(source, preview)
    assert proof.source.evidence.source_version == 1
    assert proof.annual_inputs == inputs and proof.readiness_status == 'ready'
    assert proof == recommit(proof)
    assert proof.not_evaluated == ('current_review_comments', 'filing_overrides', 'authority_permission',
        'billing_entitlement', 'technical_release', 'warning_acknowledgements')
    text = rf.serialize_rf1086_annual_readiness_v2(proof, source, preview)
    decoded = rf.parse_rf1086_annual_readiness_v2(text, source, preview)
    assert decoded == proof
    assert rf.serialize_rf1086_annual_readiness_v2(decoded, source, preview) == text
    rf.assert_rf1086_annual_readiness_matches_v2(proof, source, preview, inputs)
    with pytest.raises(FrozenInstanceError): proof.readiness_status = 'blocked'
    with pytest.raises(TypeError): proof.annual_inputs.evidence_sha256['opening'] = 'f' * 64


@pytest.mark.parametrize('changes,status,codes', [
    ({'opening_snapshot_ids': ()}, 'blocked', ('opening_balance_missing', 'opening_bank_input_missing_or_mismatched')),
    ({'opening_bank_snapshot_ids': ()}, 'blocked', ('opening_bank_input_missing_or_mismatched',)),
    ({'opening_bank_snapshot_ids': (uid(9010),)}, 'blocked', ('opening_bank_input_missing_or_mismatched',)),
    ({'unmatched_bank_count': 1}, 'blocked', ('unmatched_bank_transactions',)),
    ({'has_unpaid_items': True}, 'blocked', ('unpaid_items_not_supported',)),
    ({'authority_to_submit_confirmed': False}, 'blocked', ('annual_authority_not_confirmed',)),
    ({'period_lock_ids': ()}, 'warning', ('period_not_locked',)),
    ({'bank_balance_confirmed': False}, 'warning', ('bank_balance_not_confirmed',)),
    ({'interview_source_id': None, 'bank_balance_confirmed': None, 'has_unpaid_items': None,
      'authority_to_submit_confirmed': None}, 'warning', ('annual_data_missing',)),
    ({'period_lock_ids': (), 'bank_balance_confirmed': False}, 'warning', ('bank_balance_not_confirmed', 'period_not_locked')),
])
def test_annual_business_conditions_keep_their_existing_outcomes(changes, status, codes):
    source, preview, inputs, proof = annual(changes=changes)
    assert proof.readiness_status == status
    assert tuple(item.code for item in proof.issues) == codes
    assert proof.required_warning_codes == (codes if status == 'warning' else ())
    assert proof.accepted_warning_codes == ()
    # Same owner inputs must yield the same assessment for a legacy source.
    legacy = old_prepare(*old_basis())
    old = rf.build_rf1086_annual_readiness(legacy, preview_source(legacy)[0], inputs)
    assert (proof.readiness_status, proof.issues, proof.required_warning_codes, proof.accepted_warning_codes) == (
        old.readiness_status, old.issues, old.required_warning_codes, old.accepted_warning_codes)
    assert rf.parse_rf1086_annual_readiness_v2(rf.serialize_rf1086_annual_readiness_v2(proof, source, preview), source, preview) == proof


@pytest.mark.parametrize('label,accepted', [('aksjonaerregisteroppgaven', True),
    ('Aksjonærregisteroppgaven', True), ('RF-1086 evidence', True), ('skattemelding', False)])
def test_document_warning_ownership_and_required_warning_remain_distinct(label, accepted):
    item = rf.Rf1086AnnualDocumentStatus(uid(9011), label, 'missing_accepted_warning')
    _, _, _, proof = annual(changes={'documents': (item,), 'period_lock_ids': ()})
    assert proof.readiness_status == 'warning'
    assert proof.required_warning_codes == ('period_not_locked',)
    assert proof.accepted_warning_codes == (('missing_documents_accepted',) if accepted else ())


@pytest.mark.parametrize('changes', [
    {'company_id': rf.CompanyId(uid(9090))}, {'income_year': rf.IncomeYear(2024)},
    {'bank_transaction_count': True}, {'unmatched_bank_count': -1}, {'unmatched_bank_count': 3},
    {'period_lock_ids': ('invalid',)}, {'period_lock_ids': (uid(9012), uid(9012))},
    {'opening_snapshot_ids': (uid(9012), uid(9013))}, {'bank_balance_confirmed': 'true'},
    {'has_unpaid_items': None}, {'interview_source_id': None}, {'evidence_sha256': {}},
    {'documents': (rf.Rf1086AnnualDocumentStatus(uid(9011), 'rf-1086', 'unknown'),)},
])
def test_v2_annual_inputs_reject_malformed_or_incomplete_owner_projections(changes):
    with pytest.raises(rf.Rf1086YearSourceError, match='annual_inputs_unavailable'):
        annual(changes=changes)


@pytest.mark.parametrize('family', ['opening', 'ledger', 'banking', 'interview', 'documents'])
def test_each_owner_evidence_digest_is_bound_even_when_assessment_stays_ready(family):
    source, preview, inputs, proof = annual()
    changed = replace(inputs, evidence_sha256=dict(inputs.evidence_sha256) | {family: 'b' * 64})
    other = rf.build_rf1086_annual_readiness_v2(source, preview, changed)
    assert other.readiness_status == proof.readiness_status == 'ready'
    assert other.proof_sha256 != proof.proof_sha256
    with pytest.raises(rf.Rf1086YearSourceError, match='annual_readiness_mismatch'):
        rf.assert_rf1086_annual_readiness_matches_v2(proof, source, preview, changed)


@pytest.mark.parametrize('change', ['schema', 'source', 'inputs', 'status', 'issues', 'required', 'accepted', 'omissions', 'digest'])
def test_rehashed_annual_proof_cannot_remove_conditions_or_change_bound_evidence(change):
    source, preview, inputs, proof = annual(changes={'period_lock_ids': ()})
    if change == 'schema': proof = replace(proof, schema_version='rf1086-annual-readiness-v1')
    if change == 'source': proof = replace(proof, source=recommit(replace(proof.source, not_evaluated=())))
    if change == 'inputs': proof = replace(proof, annual_inputs=replace(inputs, period_lock_ids=(uid(9002),)))
    if change == 'status': proof = replace(proof, readiness_status='ready')
    if change == 'issues': proof = replace(proof, issues=())
    if change == 'required': proof = replace(proof, required_warning_codes=())
    if change == 'accepted': proof = replace(proof, accepted_warning_codes=('period_not_locked',))
    if change == 'omissions': proof = replace(proof, not_evaluated=())
    proof = recommit(proof)
    if change == 'digest': proof = replace(proof, proof_sha256='f' * 64)
    with pytest.raises(rf.Rf1086YearSourceError, match='annual_readiness_mismatch'):
        rf.assert_rf1086_annual_readiness_matches_v2(proof, source, preview, inputs)


@pytest.mark.parametrize('change', ['extra', 'missing', 'codec', 'v1_codec', 'whitespace', 'key_order',
    'duplicate_root', 'duplicate_nested', 'proof_record', 'source_record', 'freshness_record',
    'bool_version', 'float_version', 'unknown_field', 'missing_field', 'decimal', 'datetime', 'enum', 'nonfinite'])
def test_annual_v2_codec_is_closed_and_requires_exact_canonical_bytes(change):
    source, preview, _, proof = annual()
    text = rf.serialize_rf1086_annual_readiness_v2(proof, source, preview)
    raw = json.loads(text)
    values = raw['proof']['fields']
    evidence = values['source']['fields']['evidence']['fields']
    if change == 'extra': raw['extra'] = None
    if change == 'missing': del raw['proof']
    if change == 'codec': raw['codec'] = 'unknown'
    if change == 'v1_codec': raw['codec'] = 'rf1086-annual-readiness-v1'
    if change == 'proof_record': raw['proof']['record'] = 'Rf1086AnnualReadinessProof'
    if change == 'source_record': values['source']['record'] = 'Rf1086SourceReadinessProof'
    if change == 'freshness_record': evidence['freshness']['record'] = 'Rf1086YearSourceFreshness'
    if change == 'bool_version': evidence['source_version'] = True
    if change == 'float_version': evidence['source_version'] = 1.0
    if change == 'unknown_field': values['verified'] = True
    if change == 'missing_field': del values['not_evaluated']
    if change == 'decimal': evidence['source_version'] = {'decimal': '1'}
    if change == 'datetime': evidence['source_version'] = {'datetime': '2026-01-01T00:00:00+00:00'}
    if change == 'enum': evidence['source_version'] = {'enum': 'ActorKind', 'value': 'USER'}
    if change == 'nonfinite': evidence['source_version'] = float('nan')
    changed = json.dumps(raw, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    if change == 'whitespace': changed = text + '\n'
    if change == 'key_order': changed = json.dumps(dict(reversed(list(raw.items()))), separators=(',', ':'), ensure_ascii=False)
    if change == 'duplicate_root': changed = text[:-1] + ',"codec":"rf1086-annual-readiness-v2"}'
    if change == 'duplicate_nested': changed = text.replace('"proof_sha256":', '"proof_sha256":"' + proof.proof_sha256 + '","proof_sha256":', 1)
    assert changed != text
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        rf.parse_rf1086_annual_readiness_v2(changed, source, preview)


@pytest.mark.parametrize('change', ['schema', 'proof_hash', 'text_hash', 'text_bytes', 'extra', 'missing', 'scope', 'blocked'])
def test_v2_binding_rebuilds_proof_and_never_upgrades_blocked_readiness(change):
    from talli_backend.modules.shareholder_register_filing.annual_readiness_storage_v2 import parse_binding
    source, preview, _, proof = annual(changes={'has_unpaid_items': True} if change == 'blocked' else {})
    value = binding(proof, source, preview)
    if change == 'schema': value['schemaVersion'] = 'rf1086-annual-readiness-binding-v1'
    if change == 'proof_hash': value['proofSha256'] = 'f' * 64
    if change == 'text_hash': value['proofTextSha256'] = 'f' * 64
    if change == 'text_bytes':
        value['proofText'] += '\n'
        value['proofTextSha256'] = sha256(value['proofText'].encode()).hexdigest()
    if change == 'extra': value['verified'] = True
    if change == 'missing': del value['proofSha256']
    if change == 'scope': preview = replace(preview, income_year=rf.IncomeYear(2024))
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        parse_binding(value, source, preview)


@pytest.mark.parametrize('warning', [False, True])
def test_valid_v2_annual_binding_is_independent_from_old_binding_and_approval(warning):
    from talli_backend.modules.shareholder_register_filing.annual_readiness_storage_v2 import parse_binding
    from talli_backend.modules.shareholder_register_filing.annual_readiness_storage import parse_binding as old_binding
    source, preview, inputs, proof = annual(changes={'period_lock_ids': ()} if warning else {})
    value = binding(proof, source, preview)
    assert parse_binding(value, source, preview) == proof
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        old_binding(value, source, preview)
    basis = rf.Rf1086SourceApprovalManifestBasis(source, preview, source.confirmed_by, uid(70), 'f' * 64,
        proof.required_warning_codes, annual_readiness=proof)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        rf.build_rf1086_source_approval_manifest(basis)


@pytest.mark.parametrize('direction', ['v1_to_v2', 'v2_to_v1'])
def test_annual_versions_reject_cross_substitution_at_builder_assertion_and_codec(direction):
    source, preview, _, proof = annual()
    legacy_source = old_prepare(*old_basis())
    legacy_preview = preview_source(legacy_source)[0]
    legacy = rf.build_rf1086_annual_readiness(legacy_source, legacy_preview, inputs_for(legacy_source))
    if direction == 'v1_to_v2':
        wrong_source, wrong_preview, wrong_proof = legacy_source, legacy_preview, legacy
        build, check, parse = rf.build_rf1086_annual_readiness_v2, rf.assert_rf1086_annual_readiness_matches_v2, rf.parse_rf1086_annual_readiness_v2
        text = rf.serialize_rf1086_annual_readiness(legacy, legacy_source, legacy_preview)
    else:
        wrong_source, wrong_preview, wrong_proof = source, preview, proof
        build, check, parse = rf.build_rf1086_annual_readiness, rf.assert_rf1086_annual_readiness_matches, rf.parse_rf1086_annual_readiness
        text = rf.serialize_rf1086_annual_readiness_v2(proof, source, preview)
    with pytest.raises(rf.Rf1086YearSourceError): build(wrong_source, wrong_preview, wrong_proof.annual_inputs)
    with pytest.raises(rf.Rf1086YearSourceError): check(wrong_proof, wrong_source, wrong_preview, wrong_proof.annual_inputs)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'): parse(text, wrong_source, wrong_preview)


@pytest.mark.parametrize('path', [
    ('source',), ('source', 'evidence'), ('source', 'evidence', 'freshness'),
    ('source', 'evidence', 'company_id'), ('source', 'evidence', 'income_year'),
    ('source', 'evidence', 'source_id'), ('source', 'evidence', 'preview_id'),
    ('source', 'evidence', 'freshness', 'source_id'), ('source', 'issues', 0),
    ('annual_inputs',), ('annual_inputs', 'company_id'), ('annual_inputs', 'income_year'),
    ('annual_inputs', 'documents', 0), ('issues', 0),
])
def test_annual_assertion_and_codec_reject_hash_equivalent_nested_record_mappings(path, monkeypatch):
    from talli_backend.modules.shareholder_register_filing import source_preview
    from test_rf1086_source_readiness_v2 import record_mapping, replace_nested
    render = source_preview.render_rf1086_preview
    def with_warning(case):
        result = render(case)
        return replace(result, issues=result.issues + (rf.Rf1086ReadinessIssue('warning', 'fixture_source_warning', 'Retained source warning'),))
    monkeypatch.setattr(source_preview, 'render_rf1086_preview', with_warning)
    source, preview, inputs, proof = annual(changes={'documents': (
        rf.Rf1086AnnualDocumentStatus(uid(9011), 'rf-1086', 'missing_accepted_warning'),)})
    forged = replace_nested(proof, path, record_mapping)
    assert rf.rf1086_year_source_digest(forged) == rf.rf1086_year_source_digest(proof)
    with pytest.raises(rf.Rf1086YearSourceError, match='annual_readiness_mismatch'):
        rf.assert_rf1086_annual_readiness_matches_v2(forged, source, preview, inputs)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        rf.serialize_rf1086_annual_readiness_v2(forged, source, preview)
    # A malicious stored envelope must not decode a generic mapping as a typed record.
    raw = json.loads(rf.serialize_rf1086_annual_readiness_v2(proof, source, preview))
    container, key = raw, 'proof'
    for step in path:
        node = container[key]
        container, key = (node, step) if type(step) is int else (node['fields'], step)
    container[key] = {'mapping': container[key]['fields']}
    text = json.dumps(raw, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        rf.parse_rf1086_annual_readiness_v2(text, source, preview)


@pytest.mark.parametrize('path,kind', [
    (('source',), rf.Rf1086SourceReadinessProof),
    (('source', 'evidence'), rf.Rf1086SourceReadinessEvidence),
    (('source', 'evidence', 'source_id'), rf.PreviewId),
    (('annual_inputs', 'company_id'), rf.Rf1086YearSourceId),
])
def test_annual_assertion_rejects_wrong_nested_record_types_even_when_hash_matches(path, kind):
    from test_rf1086_source_readiness_v2 import record_mapping, replace_nested
    source, preview, inputs, proof = annual()
    forged = replace_nested(proof, path, lambda value: kind(**record_mapping(value)))
    assert rf.rf1086_year_source_digest(forged) == rf.rf1086_year_source_digest(proof)
    with pytest.raises(rf.Rf1086YearSourceError, match='annual_readiness_mismatch'):
        rf.assert_rf1086_annual_readiness_matches_v2(forged, source, preview, inputs)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        rf.serialize_rf1086_annual_readiness_v2(forged, source, preview)


@pytest.mark.parametrize('path', [('source', 'evidence', 'source_version'),
    ('annual_inputs', 'bank_transaction_count'), ('annual_inputs', 'accepted_bank_warning_count')])
def test_numerically_equal_floats_do_not_replace_integer_proof_fields(path):
    from test_rf1086_source_readiness_v2 import replace_nested
    source, preview, inputs, proof = annual()
    forged = recommit(replace_nested(proof, path, float))
    with pytest.raises(rf.Rf1086YearSourceError):
        rf.assert_rf1086_annual_readiness_matches_v2(forged, source, preview, inputs)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        rf.serialize_rf1086_annual_readiness_v2(forged, source, preview)


@pytest.mark.parametrize('duplicate', [False, True])
def test_shared_annual_policy_preserves_source_blockers_and_rejects_duplicate_issue_codes(duplicate, monkeypatch):
    from talli_backend.modules.shareholder_register_filing import source_preview
    render = source_preview.render_rf1086_preview
    def with_issue(case):
        result = render(case)
        issue = (rf.Rf1086ReadinessIssue('warning', 'period_not_locked', 'Source warning') if duplicate
            else rf.Rf1086ReadinessIssue('error', 'fixture_source_blocked', 'Source blocked'))
        return replace(result, status='ready' if duplicate else 'blocked', issues=result.issues + (issue,))
    monkeypatch.setattr(source_preview, 'render_rf1086_preview', with_issue)
    if duplicate:
        with pytest.raises(rf.Rf1086YearSourceError, match='annual_inputs_unavailable'):
            annual(changes={'period_lock_ids': ()})
    else:
        _, _, _, proof = annual()
        assert proof.source.readiness_status == proof.readiness_status == 'blocked'
        assert tuple(item.code for item in proof.issues) == ('fixture_source_blocked',)
        assert not proof.required_warning_codes and not proof.accepted_warning_codes


@pytest.mark.parametrize('change', ['source_year_tag', 'annual_year_tag', 'invalid_preview_uuid', 'null_preview_uuid'])
def test_annual_v2_codec_normalizes_declared_record_constructor_errors(change):
    source, preview, _, proof = annual()
    raw = json.loads(rf.serialize_rf1086_annual_readiness_v2(proof, source, preview))
    values = raw['proof']['fields']
    evidence = values['source']['fields']['evidence']['fields']
    if change == 'source_year_tag':
        evidence['income_year']['record'] = 'PreviewId'
    elif change == 'annual_year_tag':
        values['annual_inputs']['fields']['income_year']['record'] = 'PreviewId'
    else:
        evidence['preview_id']['fields']['value'] = None if change == 'null_preview_uuid' else 'not-a-uuid'
    changed = json.dumps(raw, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        rf.parse_rf1086_annual_readiness_v2(changed, source, preview)
