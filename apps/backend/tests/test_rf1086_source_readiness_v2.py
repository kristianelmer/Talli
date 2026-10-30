"""Pure v2 commitments; no current-owner, complete-enumeration or byte authority."""
import asyncio
from dataclasses import FrozenInstanceError, fields, replace
from datetime import timedelta
from hashlib import sha256
from uuid import UUID

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CorrelationId
from test_rf1086_source_preview import preview_source
from test_rf1086_source_production import source_for
from test_rf1086_year_source import basis as old_basis, prepare as old_prepare
from test_rf1086_year_source_v2 import CONFIRMED, prepare, v2_basis


KINDS = ('no_activity', 'formation', 'dividend', 'cash_issue', 'loss_covering_reduction', 'mixed')


def source_and_preview(kind='cash_issue', *, amendments=2):
    source = prepare(*v2_basis(kind, amendments=amendments))
    return source, preview_source(source)[0]


def recommit(proof):
    content = {field.name: getattr(proof, field.name) for field in fields(proof)
        if field.name != 'proof_sha256'}
    return replace(proof, proof_sha256=rf.rf1086_year_source_digest(content))


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('amendments', [0, 1, 2])
def test_v2_readiness_binds_complete_typed_source_without_changing_rendering(kind, amendments):
    source, preview = source_and_preview(kind, amendments=amendments)
    legacy_preview = preview_source(source_for(source.command.case))[0]
    assert (preview.preview_text, preview.hovedskjema_xml, preview.underskjema_xml,
        preview.readiness_status, preview.readiness_issues, preview.rendering_profile) == (
        legacy_preview.preview_text, legacy_preview.hovedskjema_xml, legacy_preview.underskjema_xml,
        legacy_preview.readiness_status, legacy_preview.readiness_issues, legacy_preview.rendering_profile)
    proof = rf.build_rf1086_source_readiness_v2(source, preview)
    assert type(proof) is rf.Rf1086SourceReadinessProofV2
    assert type(proof.evidence) is rf.Rf1086SourceReadinessEvidenceV2
    assert proof.schema_version == 'rf1086-source-readiness-v2'
    assert proof.evidence.schema_version == 'rf1086-source-readiness-evidence-v2'
    assert proof.evidence.source_version == source.version == 1
    assert proof.evidence.freshness == source.freshness
    assert proof.evidence.source_sha256 == source.source_sha256
    assert proof.evidence.case_sha256 == source.case_sha256
    assert proof.evidence.preview_payload_sha256 == sha256(rf.serialize_rf1086_source_preview(preview).encode()).hexdigest()
    assert proof == recommit(proof)
    assert proof.not_evaluated == ('annual_prerequisites', 'current_review_comments', 'filing_overrides',
        'authority_permission', 'billing_entitlement', 'technical_release', 'warning_acknowledgements')
    documents = {item.document_id: item for item in source.command.documents}
    for receipt in source.governance_receipts:
        if receipt.register_observation is not None:
            for original in receipt.register_observation.command.documents:
                assert documents[original.document_id].metadata_sha256 == original.metadata_sha256
    rf.assert_rf1086_source_readiness_matches_v2(proof, source, preview)
    with pytest.raises(FrozenInstanceError): proof.readiness_status = 'ready'


@pytest.mark.parametrize('previous_codec', [1, 2])
def test_explicit_correction_changes_proof_even_when_filing_bytes_stay_equal(previous_codec):
    command, context = v2_basis('no_activity')
    previous = old_prepare(*old_basis()) if previous_codec == 1 else prepare(command, context)
    previous_preview = preview_source(previous)[0]
    previous_proof = (rf.build_rf1086_source_readiness if previous_codec == 1 else rf.build_rf1086_source_readiness_v2)(previous, previous_preview)
    correction = replace(command, supersedes_source_id=previous.source_id,
        supersedes_source_sha256=previous.source_sha256, correction_reason='Reviewed v2 evidence')
    source = prepare(correction, context, previous=previous,
        source_id=rf.Rf1086YearSourceId(str(UUID(int=970))), confirmed_at=CONFIRMED + timedelta(days=1))
    preview = preview_source(source)[0]
    proof = rf.build_rf1086_source_readiness_v2(source, preview)
    assert proof.evidence.source_version == 2 and proof.schema_version.endswith('-v2')
    assert preview.hovedskjema_xml == previous_preview.hovedskjema_xml
    assert preview.underskjema_xml == previous_preview.underskjema_xml
    assert proof.proof_sha256 != previous_proof.proof_sha256
    selected = replace(preview, preview_id=rf.PreviewId(str(UUID(int=971))))
    assert rf.build_rf1086_source_readiness_v2(source, selected).proof_sha256 != proof.proof_sha256
    with pytest.raises(rf.Rf1086YearSourceError):
        rf.assert_rf1086_source_readiness_matches_v2(previous_proof, source, preview)


@pytest.mark.parametrize('field', ['company_identity_sha256', 'documents_sha256', 'governance_receipts_sha256',
    'governance_original_enumeration_sha256', 'governance_chain_enumeration_sha256', 'governance_projection_sha256'])
def test_v2_freshness_commitments_cannot_be_changed_even_with_rehashed_proof(field):
    source, preview = source_and_preview()
    proof = rf.build_rf1086_source_readiness_v2(source, preview)
    changed = replace(source.freshness, **{field: 'e' * 64})
    forged = recommit(replace(proof, evidence=replace(proof.evidence, freshness=changed)))
    with pytest.raises(rf.Rf1086YearSourceError, match='source_readiness_mismatch'):
        rf.assert_rf1086_source_readiness_matches_v2(forged, source, preview)
    with pytest.raises(rf.Rf1086YearSourceError):
        rf.build_rf1086_source_readiness_v2(replace(source, freshness=changed), preview)


@pytest.mark.parametrize('change', ['schema', 'evidence_schema', 'company', 'year', 'source', 'source_version',
    'bool_version', 'source_hash', 'case_hash', 'preview', 'payload', 'profile', 'status', 'issues', 'omissions', 'digest'])
def test_rehashed_proof_cannot_relabel_bound_evidence_or_assessment(change):
    source, preview = source_and_preview()
    proof = rf.build_rf1086_source_readiness_v2(source, preview)
    evidence = {
        'evidence_schema': {'schema_version': 'rf1086-source-readiness-evidence-v1'},
        'company': {'company_id': rf.CompanyId(str(UUID(int=972)))},
        'year': {'income_year': rf.IncomeYear(2024)},
        'source': {'source_id': rf.Rf1086YearSourceId(str(UUID(int=973)))},
        'source_version': {'source_version': 2}, 'bool_version': {'source_version': True},
        'source_hash': {'source_sha256': 'f' * 64}, 'case_hash': {'case_sha256': 'f' * 64},
        'preview': {'preview_id': rf.PreviewId(str(UUID(int=974)))}, 'payload': {'preview_payload_sha256': 'f' * 64},
        'profile': {'rendering_profile': 'unknown'},
    }
    if change in evidence: proof = replace(proof, evidence=replace(proof.evidence, **evidence[change]))
    if change == 'schema': proof = replace(proof, schema_version='rf1086-source-readiness-v1')
    if change == 'status': proof = replace(proof, readiness_status='blocked')
    if change == 'issues': proof = replace(proof, issues=(rf.Rf1086ReadinessIssue('warning', 'invented', 'Invented'),))
    if change == 'omissions': proof = replace(proof, not_evaluated=())
    proof = recommit(proof)
    if change == 'digest': proof = replace(proof, proof_sha256='f' * 64)
    with pytest.raises(rf.Rf1086YearSourceError, match='source_readiness_mismatch'):
        rf.assert_rf1086_source_readiness_matches_v2(proof, source, preview)


@pytest.mark.parametrize('field,value', [('company_id', rf.CompanyId(str(UUID(int=975)))),
    ('income_year', rf.IncomeYear(2024)), ('source_sha256', 'f' * 64), ('case_sha256', 'f' * 64),
    ('preview_text', 'changed'), ('hovedskjema_xml', '<changed/>'), ('underskjema_xml', {}),
    ('rendering_profile', 'unknown'), ('readiness_status', 'blocked')])
def test_v2_builder_rejects_a_preview_that_no_longer_matches_full_render(field, value):
    source, preview = source_and_preview()
    with pytest.raises(rf.Rf1086YearSourceError):
        rf.build_rf1086_source_readiness_v2(source, replace(preview, **{field: value}))


@pytest.mark.parametrize('direction', ['v1_to_v2', 'v2_to_v1'])
def test_versioned_readiness_builders_reject_the_other_source_type(direction):
    if direction == 'v1_to_v2':
        source = old_prepare(*old_basis())
        builder = rf.build_rf1086_source_readiness_v2
    else:
        source = prepare()
        builder = rf.build_rf1086_source_readiness
    with pytest.raises(rf.Rf1086YearSourceError): builder(source, preview_source(source)[0])


@pytest.mark.parametrize('method', ['read_readiness', 'read_annual_readiness'])
def test_pure_v2_readiness_does_not_activate_runtime_admission(method):
    from test_rf1086_source_admission import AdmissionHarness
    h = AdmissionHarness()
    h.source, h.preview = source_and_preview('no_activity')
    h.current = h.source
    with pytest.raises(rf.Rf1086YearSourceError):
        asyncio.run(getattr(h.workflow, method)('token', company_id=h.source.company_id,
            income_year=h.source.income_year, preview_id=h.preview.preview_id,
            correlation_id=CorrelationId('v2-pure-only')))
    assert h.calls == [] and not h.held and not h.committed


def replace_nested(value, path, transform):
    if not path:
        return transform(value)
    name, *rest = path
    if type(name) is int:
        return tuple(replace_nested(item, rest, transform) if index == name else item
            for index, item in enumerate(value))
    return replace(value, **{name: replace_nested(getattr(value, name), rest, transform)})


def record_mapping(value):
    return {field.name: getattr(value, field.name) for field in fields(value)}


@pytest.mark.parametrize('path', [
    ('evidence',), ('evidence', 'company_id'), ('evidence', 'income_year'),
    ('evidence', 'source_id'), ('evidence', 'preview_id'), ('evidence', 'freshness'),
    ('evidence', 'freshness', 'source_id'), ('issues', 0),
])
def test_source_proof_rejects_nested_record_mappings_with_identical_generic_hash(path, monkeypatch):
    from talli_backend.modules.shareholder_register_filing import source_preview
    render = source_preview.render_rf1086_preview
    def with_warning(case):
        result = render(case)
        return replace(result, issues=result.issues + (rf.Rf1086ReadinessIssue('warning', 'fixture_source_warning', 'Retained source warning'),))
    monkeypatch.setattr(source_preview, 'render_rf1086_preview', with_warning)
    source, preview = source_and_preview()
    proof = rf.build_rf1086_source_readiness_v2(source, preview)
    forged = replace_nested(proof, path, record_mapping)
    # The digest alone cannot distinguish these records from plain mappings.
    assert rf.rf1086_year_source_digest(forged) == rf.rf1086_year_source_digest(proof)
    with pytest.raises(rf.Rf1086YearSourceError, match='source_readiness_mismatch'):
        rf.assert_rf1086_source_readiness_matches_v2(forged, source, preview)


@pytest.mark.parametrize('path,kind', [
    (('evidence',), rf.Rf1086SourceReadinessEvidence),
    (('evidence', 'source_id'), rf.PreviewId),
    (('evidence', 'company_id'), rf.Rf1086YearSourceId),
    (('evidence', 'preview_id'), rf.Rf1086YearSourceId),
])
def test_source_proof_rejects_wrong_record_types_with_identical_fields(path, kind):
    source, preview = source_and_preview()
    proof = rf.build_rf1086_source_readiness_v2(source, preview)
    forged = replace_nested(proof, path, lambda value: kind(**record_mapping(value)))
    assert rf.rf1086_year_source_digest(forged) == rf.rf1086_year_source_digest(proof)
    with pytest.raises(rf.Rf1086YearSourceError, match='source_readiness_mismatch'):
        rf.assert_rf1086_source_readiness_matches_v2(forged, source, preview)
