"""Exact RF source readiness, without implying paid or annual release readiness."""
import asyncio
from dataclasses import FrozenInstanceError, fields, replace
from datetime import timedelta
import hashlib
from uuid import UUID

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CorrelationId
from test_rf1086_source_admission import AdmissionHarness
from test_rf1086_source_preview import preview_source
from test_rf1086_source_production import source_case, source_for
from test_rf1086_year_source import ACTOR, COMPANY, YEAR, NOW, basis, prepare


def source_and_preview():
    source = prepare(*basis())
    return source, preview_source(source)[0]


@pytest.mark.parametrize('kind', ['no_activity', 'formation', 'dividend', 'cash_issue',
    'cash_nominal_increase', 'loss_covering_reduction', 'mixed'])
def test_supported_full_year_cases_have_exact_versioned_source_evidence(kind):
    case = source_case(kind)
    if kind == 'mixed':
        case = replace(case, share_snapshot=replace(case.share_snapshot, previous_paid_in_premium=0))
    source = source_for(case)
    preview = preview_source(source)[0]
    proof = rf.build_rf1086_source_readiness(source, preview)
    assert proof.schema_version == 'rf1086-source-readiness-v1'
    assert proof.evidence.schema_version == 'rf1086-source-readiness-evidence-v1'
    assert proof.evidence.company_id == source.company_id
    assert proof.evidence.income_year == source.income_year
    assert proof.evidence.source_id == source.source_id
    assert proof.evidence.source_version == source.version
    assert proof.evidence.source_sha256 == source.source_sha256
    assert proof.evidence.case_sha256 == source.case_sha256
    assert proof.evidence.freshness == source.freshness
    assert proof.evidence.preview_id == preview.preview_id
    assert proof.evidence.preview_payload_sha256 == hashlib.sha256(
        rf.serialize_rf1086_source_preview(preview).encode('utf-8')).hexdigest()
    assert proof.evidence.rendering_profile == preview.rendering_profile
    assert proof.readiness_status == 'ready' and proof.issues == preview.readiness_issues
    assert proof == rf.build_rf1086_source_readiness(source, preview)
    rf.assert_rf1086_source_readiness_matches(proof, source, preview)
    content = {field.name: getattr(proof, field.name) for field in fields(proof)
               if field.name != 'proof_sha256'}
    assert rf.rf1086_year_source_digest(content) == proof.proof_sha256
    assert proof.not_evaluated == ('annual_prerequisites', 'current_review_comments',
        'filing_overrides', 'authority_permission', 'billing_entitlement',
        'technical_release', 'warning_acknowledgements')
    with pytest.raises(FrozenInstanceError):
        proof.readiness_status = 'blocked'


def test_same_xml_correction_or_different_selected_preview_changes_proof():
    source, preview = source_and_preview()
    before = rf.build_rf1086_source_readiness(source, preview)
    command, context = basis()
    corrected = prepare(replace(command, supersedes_source_id=source.source_id,
        supersedes_source_sha256=source.source_sha256, correction_reason='Evidence corrected'),
        context, previous=source, source_id=rf.Rf1086YearSourceId(str(UUID(int=93))),
        confirmed_at=NOW + timedelta(days=1))
    corrected_preview = preview_source(corrected)[0]
    assert corrected_preview.hovedskjema_xml == preview.hovedskjema_xml
    assert corrected_preview.underskjema_xml == preview.underskjema_xml
    after = rf.build_rf1086_source_readiness(corrected, corrected_preview)
    assert before.proof_sha256 != after.proof_sha256
    assert after.evidence.source_version == source.version + 1
    with pytest.raises(rf.Rf1086YearSourceError, match='source_readiness_mismatch'):
        rf.assert_rf1086_source_readiness_matches(before, corrected, corrected_preview)
    other_preview = replace(preview, preview_id=rf.PreviewId(str(UUID(int=94))))
    assert rf.build_rf1086_source_readiness(source, other_preview).proof_sha256 != before.proof_sha256


@pytest.mark.parametrize('mutation', ['source_hash', 'source_version', 'freshness', 'source_company',
    'preview_company', 'preview_year', 'preview_source', 'preview_text', 'xml', 'profile', 'issues', 'status'])
def test_invalid_or_mismatched_source_and_preview_never_produce_proof(mutation):
    source, preview = source_and_preview()
    if mutation == 'source_hash': source = replace(source, source_sha256='f' * 64)
    if mutation == 'source_version': source = replace(source, version=2)
    if mutation == 'freshness': source = replace(source, freshness=replace(source.freshness, documents_sha256='f' * 64))
    if mutation == 'source_company': source = replace(source, company_id=type(COMPANY)(str(UUID(int=101))))
    if mutation == 'preview_company': preview = replace(preview, company_id=type(COMPANY)(str(UUID(int=101))))
    if mutation == 'preview_year': preview = replace(preview, income_year=type(YEAR)(2024))
    if mutation == 'preview_source': preview = replace(preview, source_id=rf.Rf1086YearSourceId(str(UUID(int=102))))
    if mutation == 'preview_text': preview = replace(preview, preview_text='changed')
    if mutation == 'xml': preview = replace(preview, underskjema_xml={'owner': '<changed/>'})
    if mutation == 'profile': preview = replace(preview, rendering_profile='unknown')
    if mutation == 'issues': preview = replace(preview, readiness_issues=(rf.Rf1086ReadinessIssue('warning', 'unreviewed', 'Changed'),))
    if mutation == 'status': preview = replace(preview, readiness_status='blocked')
    with pytest.raises(rf.Rf1086YearSourceError):
        rf.build_rf1086_source_readiness(source, preview)


@pytest.mark.parametrize('mutation', ['version', 'evidence_version', 'company', 'year', 'source',
    'source_version', 'source_hash', 'case_hash', 'freshness', 'preview', 'payload', 'rendering',
    'status', 'issues', 'scope', 'digest', 'boolean_version'])
def test_exact_proof_verification_rejects_forged_scope_and_identity(mutation):
    source, preview = source_and_preview()
    proof = rf.build_rf1086_source_readiness(source, preview)
    changes = {
        'evidence_version': {'schema_version': 'rf1086-source-v1'},
        'company': {'company_id': type(COMPANY)(str(UUID(int=103)))},
        'year': {'income_year': type(YEAR)(2024)},
        'source': {'source_id': rf.Rf1086YearSourceId(str(UUID(int=104)))},
        'source_version': {'source_version': 2}, 'boolean_version': {'source_version': True},
        'source_hash': {'source_sha256': 'f' * 64}, 'case_hash': {'case_sha256': 'f' * 64},
        'freshness': {'freshness': replace(source.freshness, company_identity_sha256='f' * 64)},
        'preview': {'preview_id': rf.PreviewId(str(UUID(int=105)))},
        'payload': {'preview_payload_sha256': 'f' * 64}, 'rendering': {'rendering_profile': 'unknown'},
    }
    if mutation in changes: proof = replace(proof, evidence=replace(proof.evidence, **changes[mutation]))
    if mutation == 'version': proof = replace(proof, schema_version='rf1086-source-v1')
    if mutation == 'status': proof = replace(proof, readiness_status='blocked')
    if mutation == 'issues': proof = replace(proof, issues=(rf.Rf1086ReadinessIssue('error', 'changed', 'Changed'),))
    if mutation == 'scope': proof = replace(proof, not_evaluated=())
    if mutation == 'digest': proof = replace(proof, proof_sha256='f' * 64)
    with pytest.raises(rf.Rf1086YearSourceError, match='source_readiness_mismatch'):
        rf.assert_rf1086_source_readiness_matches(proof, source, preview)


def read(h, **kwargs):
    return asyncio.run(h.workflow.read_readiness('token', company_id=kwargs.get('company_id', COMPANY),
        income_year=kwargs.get('income_year', YEAR), preview_id=h.preview.preview_id,
        correlation_id=CorrelationId('source-readiness')))


@pytest.mark.parametrize('kind', ['no_activity', 'formation', 'transfer', 'dividend'])
def test_read_builds_inside_admission_after_bytes_and_guarded_owner_checks(kind, monkeypatch):
    h = AdmissionHarness(kind)
    builder = rf.build_rf1086_source_readiness
    def checked_builder(source, preview):
        assert h.held and h.calls[-1] == 'governance'
        h.calls.append('readiness')
        return builder(source, preview)
    monkeypatch.setattr(rf, 'build_rf1086_source_readiness', checked_builder)
    proof = read(h)
    assert proof.evidence.source_sha256 == h.source.source_sha256
    assert h.calls == ['bytes', 'guard', 'identity', 'source', 'preview', 'original',
        'governance', 'readiness', 'release']
    assert h.committed and not h.held
    # This harness has no paid entitlement, approval or legacy readiness writer.
    assert not hasattr(h.transaction, 'read_source_approval_context')


@pytest.mark.parametrize('mutation', ['identity', 'governance', 'source', 'original', 'owner', 'preview'])
def test_changes_during_preflight_never_return_a_readiness_proof(mutation):
    h = AdmissionHarness()
    def change():
        if mutation == 'identity': h.identity = replace(h.identity, company=replace(h.identity.company, name='Renamed AS'))
        if mutation == 'governance': h.view = replace(h.view, enumeration_sha256='f' * 64)
        if mutation == 'source': h.current = None
        if mutation == 'original': h.receipt_failure = True
        if mutation == 'owner': h.transaction.actor_id = type(ACTOR)(ACTOR.kind, str(UUID(int=106)))
        if mutation == 'preview': h.preview = replace(h.preview, preview_id=rf.PreviewId(str(UUID(int=107))))
    h.on_guard = change
    with pytest.raises(rf.Rf1086YearSourceError): read(h)
    assert not h.committed and not h.held


@pytest.mark.parametrize('scope', [{'company_id': type(COMPANY)(str(UUID(int=108)))},
    {'income_year': type(YEAR)(2024)}], ids=['company', 'year'])
def test_read_scope_mismatch_fails_before_original_io(scope):
    h = AdmissionHarness()
    with pytest.raises(rf.Rf1086YearSourceError): read(h, **scope)
    assert h.calls == []


def test_returned_proof_does_not_authorize_a_later_read_after_source_changes():
    h = AdmissionHarness()
    proof = read(h)
    assert proof.readiness_status == 'ready'
    h.current = None
    with pytest.raises(rf.Rf1086YearSourceError): read(h)
