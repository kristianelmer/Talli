"""Independent retained dispatch attacks; no writer, provider or admission proof."""
from dataclasses import replace

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_archive_storage_v6 import submitted_v6, query


def inspect(archive, endpoint):
    if endpoint == 'assess':
        return rf.assess_rf1086_retained_source_dispatch(archive, query=query(archive),
            submission_id=archive.source_submission_claims[0].submission_id)
    return rf.inspect_rf1086_retained_source_dispatch_position(archive, query=query(archive),
        approval_id=rf.ApprovalId(archive.approvals[0].id))


@pytest.mark.parametrize('endpoint', ['assess', 'position', 'unclaimed-position'])
@pytest.mark.parametrize('omit_overrides', [False, True])
def test_v3_cannot_erase_history_and_withdrawal_coverage_together(endpoint, omit_overrides):
    archive = submitted_v6('approved')
    if endpoint == 'unclaimed-position':
        archive = replace(archive, production_submissions=(), source_submission_claims=(),
            submission_head=None, production_events=(), feedback_artifacts=())
    archive = replace(archive, source_history=None, withdrawal_capture_records=None,
        **({'overrides': None} if omit_overrides else {}))
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        inspect(archive, endpoint)


@pytest.mark.parametrize('endpoint', ['assess', 'position'])
@pytest.mark.parametrize('shape', ['actor-subclass', 'raw-subject'])
def test_new_readers_require_typed_user_actor_consistently(endpoint, shape):
    from talli_backend.shared.kernel import ActorId, ActorKind
    archive = submitted_v6('approved')
    original = query(archive)
    class ActorSubclass(ActorId):
        pass
    actor = (ActorSubclass(ActorKind.USER, original.actor_id.subject)
        if shape == 'actor-subclass' else ActorId(ActorKind.USER, str(original.actor_id.subject)))
    changed = replace(original, actor_id=actor)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        if endpoint == 'assess':
            rf.assess_rf1086_retained_source_dispatch(archive, query=changed,
                submission_id=archive.source_submission_claims[0].submission_id)
        else:
            rf.inspect_rf1086_retained_source_dispatch_position(archive, query=changed,
                approval_id=rf.ApprovalId(archive.approvals[0].id))


@pytest.mark.parametrize('endpoint', ['assess', 'position'])
@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('status', ['approved', 'accepted'])
def test_legacy_unknown_sections_still_preserve_original_position(endpoint, version, status, monkeypatch):
    from test_rf1086_source_submission_archive import source_submission_archive
    from test_rf1086_source_dispatch import annual_submission
    from test_rf1086_archive_storage_v6 import forbid_fresh
    archive = (source_submission_archive if version == 1 else annual_submission)(status=status)
    assert archive.source_history is archive.overrides is archive.withdrawal_capture_records is None
    if endpoint == 'assess':
        expected = rf.assess_rf1086_source_dispatch(archive, query=query(archive),
            submission_id=archive.source_submission_claims[0].submission_id)
    else:
        expected = rf.inspect_rf1086_source_dispatch_position(archive, query=query(archive),
            approval_id=rf.ApprovalId(archive.approvals[0].id))
    forbid_fresh(monkeypatch)
    assert inspect(archive, endpoint) == expected


def mixed_without_history():
    """A coherent v1 selected submission plus unrelated unclaimed v3 approval.

    Re-identify the v1 preview through its real builder to avoid duplicate IDs;
    captured history is deliberately unknown, exposing the new boundary check.
    """
    from hashlib import sha256
    import json
    from uuid import UUID
    from test_rf1086_source_submission_archive import source_submission_archive
    from test_rf1086_year_source import ACTOR
    legacy = source_submission_archive(status='approved')
    line, approval = legacy.source_approval_lineage[0], legacy.approvals[0]
    preview = replace(line.source_preview, preview_id=rf.PreviewId(str(UUID(int=9701))))
    payload_hash = sha256(rf.serialize_rf1086_source_preview(preview).encode()).hexdigest()
    bridge = replace(line.bridge, preview_id=preview.preview_id.value, payload_sha256=payload_hash)
    review = json.loads(line.review_text)
    review['binding'].update(preview_id=preview.preview_id.value, payload_sha256=payload_hash)
    review['scope']['previewId'] = preview.preview_id.value
    review_text = json.dumps(review, sort_keys=True, ensure_ascii=False)
    review_hash = sha256(review_text.encode()).hexdigest()
    approved = rf.build_rf1086_source_approval_manifest(rf.Rf1086SourceApprovalManifestBasis(
        line.source, preview, ACTOR, approval.entitlement_id, review_hash, ()))
    approval = replace(approval, preview_id=preview.preview_id.value, payload_hash=payload_hash,
        manifest=approved.manifest, manifest_hash=approved.manifest_sha256)
    line = replace(line, preview_id=preview.preview_id.value, payload_sha256=payload_hash,
        source_preview=preview, bridge=bridge, review_sha256=review_hash, review_text=review_text,
        manifest_sha256=approved.manifest_sha256,
        manifest_text=rf.serialize_rf1086_source_approval_manifest(approved))
    projection = replace(legacy.previews[0], id=preview.preview_id.value)
    claim = replace(legacy.source_submission_claims[0], payload_sha256=payload_hash,
        manifest_sha256=approved.manifest_sha256)
    submission = replace(legacy.production_submissions[0], payload_hash=payload_hash)
    modern = submitted_v6('approved')
    modern_approval = replace(modern.approvals[0], id=str(UUID(int=9702)))
    modern_line = replace(modern.source_approval_lineage[0], approval_id=modern_approval.id)
    return replace(legacy, previews=(projection, *modern.previews),
        approvals=(approval, modern_approval), source_approval_lineage=(line, modern_line),
        source_submission_claims=(claim,), production_submissions=(submission,))


@pytest.mark.parametrize('endpoint', ['assess', 'position'])
def test_selecting_v1_inside_mixed_archive_cannot_skip_v3_coverage(endpoint):
    from talli_backend.modules.shareholder_register_filing.preparation import _validate_retained_archive_source
    archive = mixed_without_history()
    assert archive.approvals[0].manifest['schemaVersion'] == 'production-source-approval-v1'
    assert archive.approvals[1].manifest['schemaVersion'] == 'production-source-approval-v3'
    # The shared legacy-compatible validator accepts this coherent unknown state;
    # only the new API must enforce its archive-wide v3 coverage contract.
    assert _validate_retained_archive_source(query(archive), archive) is archive
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        inspect(archive, endpoint)


@pytest.mark.parametrize('endpoint', ['assess', 'position'])
@pytest.mark.parametrize('field', ['source', 'document', 'annual'])
def test_valid_header_cannot_substitute_for_full_retained_evidence(endpoint, field):
    from hashlib import sha256
    import json
    from test_rf1086_year_source import ACTOR
    archive = submitted_v6('approved')
    approval, line = archive.approvals[0], archive.source_approval_lineage[0]
    manifest = json.loads(line.manifest_text)
    if field == 'source': manifest['source']['sha256'] = 'e' * 64
    if field == 'document': manifest['documentHashes'][0]['sha256'] = 'e' * 64
    if field == 'annual':
        binding = manifest['annualReadiness']
        binding['proofText'] = 'opaque bytes with a valid envelope checksum'
        binding['proofTextSha256'] = sha256(binding['proofText'].encode()).hexdigest()
    text = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    digest = sha256(text.encode()).hexdigest()
    approval = replace(approval, manifest=manifest, manifest_hash=digest)
    line = replace(line, manifest_text=text, manifest_sha256=digest)
    claim = replace(archive.source_submission_claims[0], manifest_sha256=digest)
    changed = replace(archive, approvals=(approval,), source_approval_lineage=(line,),
        source_submission_claims=(claim,))
    assert rf.inspect_rf1086_retained_source_approval_v3(
        rf.Rf1086RetainedSourceApproval(approval, text), approval_id=rf.ApprovalId(approval.id),
        manifest_sha256=digest, actor_id=ACTOR) is None
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        inspect(changed, endpoint)


@pytest.mark.parametrize('index', [0, 1, 2])
@pytest.mark.parametrize('state,failure', [('prepared', None), ('unknown', 'unknown'), ('failed', 'unknown')])
def test_uncertain_v3_mutation_precedes_invalidation_at_every_stage(index, state, failure, monkeypatch):
    from test_rf1086_retained_source_dispatch import retained_submission
    from test_rf1086_archive_storage_v6 import forbid_fresh
    archive = retained_submission(status='accepted')
    rows = archive.production_events[:index + 1]
    pending = replace(rows[-1], operation_state=state, failure_class=failure,
        authority_reference=None, resulting_status='unknown')
    rows = (*rows[:-1], pending)
    refs = {row.operation_name: row.authority_reference for row in rows
        if row.operation_state == 'succeeded'}
    archive = replace(archive, production_events=rows, feedback_artifacts=(),
        production_submissions=(replace(archive.production_submissions[0],
            status='sending', feedback_state='sent', feedback_artifact_count=0, authority_references=refs),),
        approvals=(replace(archive.approvals[0], invalidated_at=archive.approvals[0].approved_at,
            invalidation_reason='Later source changes'),))
    forbid_fresh(monkeypatch)
    assessment = inspect(archive, 'assess')
    assert assessment.disposition == inspect(archive, 'position').disposition == 'recovery_required'
    assert (assessment.operation_id, assessment.attempt, assessment.idempotency_key) == (
        pending.id, pending.attempt, pending.idempotency_key)
