"""Retained codec fixtures, not a runtime archive producer or origin certificate."""
from dataclasses import asdict, replace
from decimal import Decimal
from hashlib import sha256
import json
from uuid import UUID

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.modules.shareholder_register_filing import archive_storage as old
from talli_backend.modules.shareholder_register_filing import archive_storage_v6 as retained
from test_rf1086_annual_readiness_v2 import inputs_for
from test_rf1086_archive_history import history_archive
from test_rf1086_archive_history_v6 import mixed_archive
from test_rf1086_archive_source import snapshot, production_snapshot
from test_rf1086_archive_storage import query, tamper
from test_rf1086_feedback_archive_originals import feedback_archive
from test_rf1086_override_archive import override_archive
from test_rf1086_source_approval_archive import source_archive
from test_rf1086_source_submission_archive import source_submission_archive, correction_archive
from test_rf1086_withdrawal_archive import withdrawal_archive
from test_rf1086_year_source import ACTOR


def digest(value):
    return sha256(value.encode()).hexdigest()


def approved_v6(kind='cash_issue', amendments=2, *, correction=True, annual_changes=None):
    """Actual pure source/proof builders; historical review is synthetic evidence."""
    archive, _ = mixed_archive(kind, amendments, legacy=correction, previews=True)
    source = archive.source_history.year_sources[-1]
    capture = archive.source_history.source_previews[0]
    preview = capture.preview
    template = source_archive()
    line, approval = template.source_approval_lineage[0], template.approvals[0]
    bridge = replace(line.bridge, preview_id=preview.preview_id.value,
        source_id=source.source_id.value, source_sha256=source.source_sha256,
        payload_sha256=capture.payload_sha256, created_at=capture.created_at)
    annual = rf.build_rf1086_annual_readiness_v2(source, preview,
        replace(inputs_for(source), **(annual_changes or {})))
    proof_text = rf.serialize_rf1086_annual_readiness_v2(annual, source, preview)
    binding = dict(schemaVersion='rf1086-annual-readiness-binding-v2', proofSha256=annual.proof_sha256,
        proofTextSha256=digest(proof_text), proofText=proof_text)
    review = json.loads(line.review_text)
    review.pop('storedReleaseReady')
    review.update(version='rf1086-source-review-v3', binding=asdict(bridge),
        otherOverridesReady=True, annualReadiness=binding)
    review['scope'].update(previewId=bridge.preview_id, sourceId=bridge.source_id,
        sourceSha256=bridge.source_sha256, warningCodes=list(annual.required_warning_codes))
    review_text = json.dumps(review, sort_keys=True, ensure_ascii=False)
    approved = rf.build_rf1086_source_approval_manifest_v3(rf.Rf1086SourceApprovalManifestBasisV3(
        source, preview, annual, ACTOR, approval.entitlement_id, digest(review_text), annual.required_warning_codes))
    approval = replace(approval, preview_id=bridge.preview_id, payload_hash=bridge.payload_sha256,
        manifest_hash=approved.manifest_sha256, manifest=approved.manifest, approved_at=capture.created_at)
    line = replace(line, preview_id=bridge.preview_id, source_id=bridge.source_id,
        source_sha256=bridge.source_sha256, payload_sha256=bridge.payload_sha256,
        manifest_sha256=approved.manifest_sha256, manifest_text=rf.serialize_rf1086_source_approval_manifest_v3(approved),
        review_text=review_text, review_sha256=digest(review_text), created_at=capture.created_at,
        source=source, source_preview=preview, bridge=bridge)
    projection = replace(template.previews[0], id=bridge.preview_id, status=preview.readiness_status,
        issues=preview.readiness_issues, preview=preview.preview_text, hovedskjema_xml=preview.hovedskjema_xml,
        underskjema_xml=approved.underskjema_xml, created_at=capture.created_at)
    return replace(archive, previews=(projection,), approvals=(approval,), source_approval_lineage=(line,),
        source_history=replace(archive.source_history, review_bridges=(bridge,)))


def bomb(*args, **kwargs):
    raise AssertionError('Retained reading must not render or call a fresh builder')


def forbid_fresh(monkeypatch):
    for name in ('render_rf1086_preview', 'assert_rf1086_source_preview_matches',
        'prepare_rf1086_source_preview', 'build_rf1086_source_readiness', 'build_rf1086_source_readiness_v2',
        'build_rf1086_annual_readiness', 'build_rf1086_annual_readiness_v2',
        'assert_rf1086_annual_readiness_matches', 'assert_rf1086_annual_readiness_matches_v2',
        'build_rf1086_source_approval_manifest', 'build_rf1086_source_approval_manifest_v3'):
        if hasattr(rf, name): monkeypatch.setattr(rf, name, bomb)
    from talli_backend.modules.shareholder_register_filing import source_preview, source_readiness, source_readiness_v2
    from talli_backend.modules.shareholder_register_filing import source_production, source_production_v3, annual_readiness
    for module, names in ((source_preview, ('prepare', 'assert_matches')),
                          (source_readiness, ('build',)), (source_readiness_v2, ('build',)),
                          (source_production, ('build_manifest',)), (source_production_v3, ('build_manifest',)),
                          (annual_readiness, ('build',))):
        for name in names:
            if hasattr(module, name): monkeypatch.setattr(module, name, bomb)


@pytest.mark.parametrize('builder', [snapshot, production_snapshot, lambda: history_archive()[0],
    lambda: feedback_archive()[0], lambda: override_archive()[0], lambda: withdrawal_archive()[0],
    source_archive, source_submission_archive, correction_archive])
def test_original_envelope_is_read_without_rewrapping_or_current_renderer(builder, monkeypatch):
    archive = builder()
    text = old.serialize(archive, query=query(archive))
    forbid_fresh(monkeypatch)
    parsed = retained.parse(text, query=query(archive))
    assert parsed == archive
    assert (parsed.source_history is None) == (archive.source_history is None)
    assert (parsed.overrides is None) == (archive.overrides is None)
    assert (parsed.withdrawal_capture_records is None) == (archive.withdrawal_capture_records is None)


@pytest.mark.parametrize('kind', ['no_activity', 'formation', 'dividend', 'cash_issue', 'loss_covering_reduction', 'mixed'])
@pytest.mark.parametrize('amendments', [0, 1, 2])
@pytest.mark.parametrize('correction', [False, True])
def test_complete_v6_approval_roundtrip_without_fresh_builder(kind, amendments, correction, monkeypatch):
    archive = approved_v6(kind, amendments, correction=correction)
    forbid_fresh(monkeypatch)
    text = retained.serialize(archive, query=query(archive))
    assert json.loads(text)['codec'] == 'rf1086-production-archive-v6'
    restored = retained.parse(text, query=query(archive))
    assert restored == archive
    assert retained.serialize(restored, query=query(archive)) == text
    assert restored.source_approval_lineage[0].source.version == (2 if correction else 1)
    assert restored.source_approval_lineage[0].source.governance_projection == archive.source_approval_lineage[0].source.governance_projection
    with pytest.raises(rf.Rf1086ArchiveError): old.parse(text, query=query(archive))
    with pytest.raises(rf.Rf1086ArchiveError): old.serialize(archive, query=query(archive))


@pytest.mark.parametrize('field', ['source_history', 'overrides', 'withdrawal_capture_records'])
def test_v6_does_not_turn_unknown_coverage_into_empty_capture(field):
    archive, _ = mixed_archive(amendments=0)
    with pytest.raises(rf.Rf1086ArchiveError):
        retained.serialize(replace(archive, **{field: None}), query=query(archive))


def test_v6_can_explicitly_capture_empty_legacy_history_and_preserves_json_numeric_types():
    archive = snapshot()
    numbers = {'float': 1.1, 'int': 1, 'decimal': Decimal('1.00')}
    archive = replace(archive, source_history=rf.Rf1086ArchiveSourceHistory(), overrides=(),
        withdrawal_capture_records=(), simulations=(replace(archive.simulations[0], submitted_payload=numbers),))
    text = retained.serialize(archive, query=query(archive))
    decoded = retained.parse(text, query=query(archive))
    assert decoded == archive
    for key, value in numbers.items():
        assert type(decoded.simulations[0].submitted_payload[key]) is type(value)
    assert str(decoded.simulations[0].submitted_payload['decimal']) == '1.00'


@pytest.mark.parametrize('blocked', [False, True])
def test_unapproved_noncanonical_preview_is_retained_without_approval_rules(blocked, monkeypatch):
    archive, _ = mixed_archive(previews=True)
    row = archive.source_history.source_previews[0]
    preview = replace(row.preview, readiness_status='blocked', hovedskjema_xml=None, underskjema_xml=None) if blocked else row.preview
    raw = json.dumps(json.loads(rf.serialize_rf1086_source_preview(preview)), indent=2) + '\n'
    archive = replace(archive, source_history=replace(archive.source_history, source_previews=(
        replace(row, preview=preview, payload_text=raw, payload_sha256=digest(raw)),)))
    forbid_fresh(monkeypatch)
    text = retained.serialize(archive, query=query(archive))
    assert retained.parse(text, query=query(archive)).source_history.source_previews[0].payload_text == raw


@pytest.mark.parametrize('codec', ['rf1086-production-archive-v1', 'rf1086-production-archive-v2',
    'rf1086-production-archive-v3', 'rf1086-production-archive-v4', 'rf1086-production-archive-v5'])
def test_v2_records_cannot_be_smuggled_under_legacy_codec(codec):
    archive = approved_v6()
    wire = json.loads(retained.serialize(archive, query=query(archive)))
    wire['codec'] = codec
    with pytest.raises(rf.Rf1086ArchiveError): retained.parse(json.dumps(wire), query=query(archive))


@pytest.mark.parametrize('change', ['outer-space', 'inner-space', 'duplicate-outer', 'duplicate-inner',
    'unknown-codec', 'checksum', 'unknown-record', 'extra-record-field', 'null-history', 'null-overrides',
    'null-withdrawals', 'extra-envelope', 'missing-history', 'bool-year', 'nonfinite'])
def test_closed_v6_codec_rejects_rehashed_shape_and_noncanonical_forms(change):
    archive = approved_v6()
    text = retained.serialize(archive, query=query(archive))
    wire = json.loads(text); body = json.loads(wire['snapshotText'])
    if change == 'outer-space': text = json.dumps(wire, indent=2)
    elif change == 'duplicate-outer': text = text[:-1] + ',"sha256":' + json.dumps(wire['sha256']) + '}'
    else:
        if change == 'inner-space': wire['snapshotText'] = json.dumps(body, indent=2)
        elif change == 'duplicate-inner': wire['snapshotText'] = wire['snapshotText'][:-1] + ',"record":"Rf1086ArchiveSnapshot"}'
        else:
            if change == 'unknown-record': body['record'] = 'Rf1086AnnualReadinessProofV2'
            if change == 'extra-record-field': body['fields']['unexpected'] = None
            if change.startswith('null-'): body['fields'][{'null-history':'source_history','null-overrides':'overrides','null-withdrawals':'withdrawal_capture_records'}[change]] = None
            if change == 'missing-history': del body['fields']['source_history']
            if change == 'bool-year': body['fields']['income_year']['fields']['value'] = True
            if change == 'nonfinite': body['fields']['simulations'] = [float('inf')]
            wire['snapshotText'] = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        wire['sha256'] = digest(wire['snapshotText'])
        if change == 'unknown-codec': wire['codec'] = 'rf1086-production-archive-v7'
        if change == 'checksum': wire['sha256'] = 'f' * 64
        if change == 'extra-envelope': wire['unknown'] = None
        text = json.dumps(wire, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    with pytest.raises(rf.Rf1086ArchiveError, match='rf1086_archive_storage_invalid'):
        retained.parse(text, query=query(archive))


def recommit_manifest(archive, manifest, *, review_text=None):
    text = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    approval = replace(archive.approvals[0], manifest=manifest, manifest_hash=digest(text))
    line = replace(archive.source_approval_lineage[0], manifest_text=text, manifest_sha256=digest(text))
    if review_text is not None: line = replace(line, review_text=review_text, review_sha256=digest(review_text))
    return replace(archive, approvals=(approval,), source_approval_lineage=(line,))


@pytest.mark.parametrize('field,value', [
    ('schemaVersion', 'production-source-approval-v2'), ('companyId', str(UUID(int=9911))),
    ('incomeYear', 2024), ('userId', str(UUID(int=9912))), ('organizationNumber', '987654321'),
    ('entitlementId', str(UUID(int=9913))), ('caseProfile', 'rf1086_no_activity_v1'),
    ('adapterVersion', 'rf1086-source-production-v2'), ('obligation', 'other'),
    ('documentOrderVersion', 'unknown'), ('unexpected', 'not committed by supported owner'),
])
def test_rehashed_v3_manifest_must_rebuild_every_identity_field(field, value):
    archive = approved_v6()
    manifest = json.loads(archive.source_approval_lineage[0].manifest_text)
    manifest[field] = value
    changed = recommit_manifest(archive, manifest)
    with pytest.raises(rf.Rf1086ArchiveError): retained.serialize(changed, query=query(archive))


@pytest.mark.parametrize('path', ['source.codec', 'source.id', 'source.version', 'source.sha256',
    'source.caseSha256', 'preview.id', 'preview.renderingProfile', 'preview.reviewTextSha256',
    'freshness.companyIdentitySha256', 'freshness.documentsSha256', 'freshness.governanceReceiptsSha256',
    'freshness.governanceOriginalEnumerationSha256', 'freshness.governanceChainEnumerationSha256',
    'freshness.governanceProjectionSha256', 'documentHashes'])
def test_self_consistent_manifest_hash_does_not_prove_source_or_preview_correspondence(path):
    archive = approved_v6()
    manifest = json.loads(archive.source_approval_lineage[0].manifest_text)
    if path == 'documentHashes': manifest[path][0]['sha256'] = 'f' * 64
    else:
        parent, key = path.split('.')
        manifest[parent][key] = 99 if key == 'version' else 'f' * 64
    with pytest.raises(rf.Rf1086ArchiveError):
        retained.serialize(recommit_manifest(archive, manifest), query=query(archive))


@pytest.mark.parametrize('path', ['source.version', 'incomeYear'])
def test_v3_raw_manifest_numeric_type_cannot_hide_behind_equal_python_values(path):
    archive = approved_v6(correction=False)
    manifest = json.loads(archive.source_approval_lineage[0].manifest_text)
    if path == 'source.version': manifest['source']['version'] = True
    else: manifest['incomeYear'] = float(manifest['incomeYear'])
    # Keep original integer canonical text/hash; only the stored record changes.
    changed = replace(archive, approvals=(replace(archive.approvals[0], manifest=manifest),))
    with pytest.raises(rf.Rf1086ArchiveError): retained.serialize(changed, query=query(archive))


@pytest.mark.parametrize('change', ['version-v1', 'version-v2', 'missing-annual', 'annual-v1',
    'extra', 'missing', 'permission', 'pilot', 'request', 'scope', 'binding', 'technical', 'other',
    'warning', 'hard-block', 'blocking-override', 'duplicate-key'])
def test_rehashed_review_v3_cannot_weaken_saved_release_or_scope(change):
    archive = approved_v6(annual_changes={'period_lock_ids': ()})
    line = archive.source_approval_lineage[0]
    review = json.loads(line.review_text)
    if change == 'version-v1': review['version'] = 'rf1086-source-review-v1'
    if change == 'version-v2': review['version'] = 'rf1086-source-review-v2'
    if change == 'missing-annual': review.pop('annualReadiness')
    if change == 'annual-v1': review['annualReadiness']['schemaVersion'] = 'rf1086-annual-readiness-binding-v1'
    if change == 'extra': review['storedReleaseReady'] = True
    if change == 'missing': review.pop('otherOverridesReady')
    if change == 'permission': review['permission']['confirmed_by'] = str(UUID(int=999))
    if change == 'pilot': review['pilot']['status'] = 'revoked'
    if change == 'request': review['request']['preflight_verified_at'] = None
    if change == 'scope': review['scope']['sourceSha256'] = 'f' * 64
    if change == 'binding': review['binding']['payload_sha256'] = 'f' * 64
    if change == 'technical': review['technicalReleaseReady'] = False
    if change == 'other': review['otherOverridesReady'] = False
    if change == 'warning': review['scope']['warningCodes'] = []
    if change == 'hard-block': review['comments'] = [{'id':str(UUID(int=900)), 'company_id':line.company_id,
        'preview_id':line.preview_id, 'severity':'hard_block', 'acknowledged_at':None}]
    if change == 'blocking-override': review['overrides'] = [{'id':str(UUID(int=900)),
        'company_id':line.company_id, 'income_year':line.income_year, 'risk_level':'block'}]
    text = json.dumps(review, sort_keys=True, ensure_ascii=False)
    if change == 'duplicate-key': text = text[:-1] + ',"technicalReleaseReady":true}'
    manifest = json.loads(line.manifest_text)
    manifest['review']['sha256'] = digest(text)
    with pytest.raises(rf.Rf1086ArchiveError):
        retained.serialize(recommit_manifest(archive, manifest, review_text=text), query=query(archive))


@pytest.mark.parametrize('change', ['manifest-version', 'binding-version', 'proof-hash', 'proof-text',
    'proof-policy', 'missing-warning', 'extra-warning'])
def test_annual_binding_is_reassessed_under_its_retained_version(change):
    archive = approved_v6(annual_changes={'period_lock_ids': ()})
    line = archive.source_approval_lineage[0]
    manifest = json.loads(line.manifest_text)
    review = json.loads(line.review_text)
    binding = manifest['annualReadiness']
    if change == 'manifest-version': manifest['schemaVersion'] = 'production-source-approval-v2'
    if change == 'binding-version': binding['schemaVersion'] = 'rf1086-annual-readiness-binding-v1'
    if change == 'proof-hash': binding['proofSha256'] = 'f' * 64
    if change == 'proof-text': binding['proofText'] = json.dumps(json.loads(binding['proofText']), indent=2)
    if change == 'proof-policy':
        raw = json.loads(binding['proofText']); raw['proof']['fields']['readiness_status'] = 'ready'
        binding['proofText'] = json.dumps(raw, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    if change in ('proof-text', 'proof-policy'): binding['proofTextSha256'] = digest(binding['proofText'])
    if change == 'missing-warning': manifest['review']['acknowledgedWarningCodes'] = []
    if change == 'extra-warning': manifest['review']['acknowledgedWarningCodes'].append('invented_warning')
    review['annualReadiness'] = binding
    review['scope']['warningCodes'] = manifest['review']['acknowledgedWarningCodes']
    text = json.dumps(review, sort_keys=True, ensure_ascii=False)
    manifest['review']['sha256'] = digest(text)
    with pytest.raises(rf.Rf1086ArchiveError):
        retained.serialize(recommit_manifest(archive, manifest, review_text=text), query=query(archive))


def submitted_v6(status='accepted'):
    """Captured submission/journal values only; no v3 claim or send API is enabled."""
    archive = approved_v6()
    template = source_submission_archive('cash_issue', 'approved' if status == 'unknown' else status)
    approval, line = archive.approvals[0], archive.source_approval_lineage[0]
    submission = replace(template.production_submissions[0], approval_id=approval.id,
        entitlement_id=approval.entitlement_id, user_id=approval.user_id, submitted_by=approval.approved_by,
        payload_hash=approval.payload_hash, adapter_version=approval.adapter_version)
    claim = replace(template.source_submission_claims[0], approval_id=rf.ApprovalId(approval.id),
        manifest_sha256=approval.manifest_hash, payload_sha256=approval.payload_hash, claimed_at=line.created_at)
    documents = {('post_hovedskjema' if d['name'] == 'hovedskjema' else
        'post_underskjema:' + d['name'].removeprefix('underskjema_')):d['sha256']
        for d in approval.manifest['documentHashes']}
    events = tuple(replace(event, body_hash=documents[event.operation_name])
        if event.operation_name in documents else event for event in template.production_events)
    if status == 'unknown':
        event = source_submission_archive('cash_issue').production_events[0]
        events = (replace(event, operation_state='unknown', resulting_status='unknown',
            body_hash=documents['post_hovedskjema'], authority_reference=None,
            artifact_hashes=(), failure_class='unknown'),)
        submission = replace(submission, status='unknown', failure_class='unknown')
    return replace(archive, production_submissions=(submission,), source_submission_claims=(claim,),
        submission_head=replace(template.submission_head, updated_at=claim.claimed_at),
        production_events=events, feedback_artifacts=template.feedback_artifacts)


@pytest.mark.parametrize('status', ['approved', 'accepted', 'rejected', 'unknown'])
def test_retained_v3_claim_journal_and_feedback_need_no_fresh_send_authority(status, monkeypatch):
    archive = submitted_v6(status)
    forbid_fresh(monkeypatch)
    text = rf.serialize_rf1086_archive_v6(archive, query=query(archive))
    restored = rf.parse_rf1086_retained_archive(text, query=query(archive))
    assert restored == archive
    assert restored.production_submissions[0].status == status
    # The existing live claim-inspection contract deliberately remains v1/v2.
    with pytest.raises(rf.Rf1086ProductionError):
        rf.inspect_rf1086_retained_source_approval(
            rf.Rf1086RetainedSourceApproval(archive.approvals[0], archive.source_approval_lineage[0].manifest_text),
            approval_id=rf.ApprovalId(archive.approvals[0].id),
            manifest_sha256=archive.approvals[0].manifest_hash, actor_id=ACTOR)


@pytest.mark.parametrize('change', ['missing-claim', 'claim-hash', 'claim-actor', 'missing-head',
    'head-parent', 'missing-post', 'missing-confirmation', 'changed-body', 'changed-key',
    'missing-feedback', 'missing-reconciliation', 'feedback-sha', 'artifact-count', 'duplicate-journal'])
def test_v3_retained_submission_inherits_existing_complete_journal_and_feedback_checks(change):
    archive = submitted_v6()
    claim = archive.source_submission_claims[0]
    events = archive.production_events
    if change == 'missing-claim': archive = replace(archive, source_submission_claims=())
    if change == 'claim-hash': archive = replace(archive, source_submission_claims=(replace(claim, manifest_sha256='f' * 64),))
    if change == 'claim-actor': archive = replace(archive, source_submission_claims=(replace(claim,
        claimed_by=replace(ACTOR, subject=type(ACTOR.subject)(str(UUID(int=9111))))),))
    if change == 'missing-head': archive = replace(archive, submission_head=None)
    if change == 'head-parent': archive = replace(archive, submission_head=replace(archive.submission_head,
        submission_id=rf.SubmissionId(str(UUID(int=9111)))))
    if change == 'missing-post': archive = replace(archive, production_events=events[1:])
    if change == 'missing-confirmation': archive = replace(archive, production_events=tuple(row for row in events if row.operation_name != 'confirm'))
    if change == 'changed-body': archive = replace(archive, production_events=(replace(events[0], body_hash='f' * 64), *events[1:]))
    if change == 'changed-key': archive = replace(archive, production_events=(replace(events[0], idempotency_key=None), *events[1:]))
    if change == 'missing-feedback': archive = replace(archive, feedback_artifacts=())
    if change == 'missing-reconciliation': archive = replace(archive, production_events=tuple(row for row in events if not row.operation_name.startswith('reconciliation:')))
    if change == 'feedback-sha': archive = replace(archive, feedback_artifacts=(replace(archive.feedback_artifacts[0], sha256='f' * 64),))
    if change == 'artifact-count': archive = replace(archive, production_submissions=(replace(archive.production_submissions[0], feedback_artifact_count=0),))
    if change == 'duplicate-journal': archive = replace(archive, production_events=(*events, events[0]))
    with pytest.raises(rf.Rf1086ArchiveError): rf.serialize_rf1086_archive_v6(archive, query=query(archive))


def test_v3_submission_correction_preserves_terminal_parent_and_exact_predecessor_identity(monkeypatch):
    parent = submitted_v6()
    approval, line = parent.approvals[0], parent.source_approval_lineage[0]
    prior = dict(submissionId=parent.production_submissions[0].id,
        manifestSha256=approval.manifest_hash, reason=' Retained correction\nårsaken ')
    manifest = json.loads(line.manifest_text); manifest['predecessor'] = prior
    child = recommit_manifest(parent, manifest)
    child_approval = replace(child.approvals[0], id=str(UUID(int=9112)))
    child_line = replace(child.source_approval_lineage[0], approval_id=child_approval.id)
    child_submission = replace(parent.production_submissions[0], id=str(UUID(int=9113)),
        approval_id=child_approval.id, status='approved', feedback_state='sent',
        feedback_artifact_count=0, authority_references={}, supersedes_submission_id=prior['submissionId'])
    child_claim = replace(parent.source_submission_claims[0], submission_id=rf.SubmissionId(child_submission.id),
        approval_id=rf.ApprovalId(child_approval.id), manifest_sha256=child_approval.manifest_hash,
        predecessor_submission_id=rf.SubmissionId(prior['submissionId']))
    archive = replace(parent, approvals=(approval, child_approval), source_approval_lineage=(line, child_line),
        production_submissions=(*parent.production_submissions, child_submission),
        source_submission_claims=(*parent.source_submission_claims, child_claim),
        submission_head=replace(parent.submission_head, submission_id=child_claim.submission_id))
    forbid_fresh(monkeypatch)
    text = rf.serialize_rf1086_archive_v6(archive, query=query(archive))
    assert rf.parse_rf1086_retained_archive(text, query=query(archive)) == archive
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.serialize_rf1086_archive_v6(replace(archive, production_submissions=(child_submission,)), query=query(archive))
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.serialize_rf1086_archive_v6(replace(archive, submission_head=parent.submission_head), query=query(archive))


def test_explicit_retained_api_does_not_change_old_parser_validation_semantics(monkeypatch):
    archive = source_archive()
    text = rf.serialize_rf1086_archive(archive, query=query(archive))
    forbid_fresh(monkeypatch)
    assert rf.parse_rf1086_retained_archive(text, query=query(archive)) == archive
    with pytest.raises(AssertionError, match='Retained reading must not render'):
        rf.parse_rf1086_archive(text, query=query(archive))


@pytest.mark.parametrize('builder', [snapshot, lambda: history_archive()[0],
    lambda: feedback_archive()[0], lambda: override_archive()[0], lambda: withdrawal_archive()[0]])
def test_original_noncanonical_legacy_envelope_hashes_original_snapshot_text(builder):
    archive = builder()
    wire = json.loads(rf.serialize_rf1086_archive(archive, query=query(archive)))
    wire['snapshotText'] = json.dumps(json.loads(wire['snapshotText']), indent=2, ensure_ascii=False) + '\n'
    wire['sha256'] = digest(wire['snapshotText'])
    text = json.dumps(wire, indent=3, ensure_ascii=False) + '\n'
    assert rf.parse_rf1086_archive(text, query=query(archive)) == archive
    assert rf.parse_rf1086_retained_archive(text, query=query(archive)) == archive


def test_off_year_company_evidence_stays_bound_without_inventing_local_capture():
    from test_rf1086_archive_history_v6 import replace_projection
    from test_rf1086_year_source_v2 import prepare, v2_basis
    archive, context = mixed_archive('no_activity', amendments=0)
    capital = prepare(*v2_basis('cash_issue', amendments=2))
    off_year = replace(capital.governance_projection.chains[0], income_year=rf.IncomeYear(2024))
    archive = replace_projection(archive, context, (off_year,))
    text = rf.serialize_rf1086_archive_v6(archive, query=query(archive))
    restored = rf.parse_rf1086_retained_archive(text, query=query(archive))
    assert restored.source_history.year_sources[0].governance_projection.chains == (off_year,)
    assert restored.source_history.register_observations == ()
    assert restored.withdrawal_capture_records == ()


def test_approved_preview_cannot_replace_canonical_commitment_with_rehashed_pretty_json():
    archive = approved_v6()
    line = archive.source_approval_lineage[0]
    record = archive.source_history.source_previews[0]
    raw = json.dumps(json.loads(record.payload_text), indent=2) + '\n'
    bridge = replace(line.bridge, payload_sha256=digest(raw))
    review = json.loads(line.review_text); review['binding'] = asdict(bridge)
    review_text = json.dumps(review, sort_keys=True, ensure_ascii=False)
    manifest = json.loads(line.manifest_text); manifest['review']['sha256'] = digest(review_text)
    archive = recommit_manifest(archive, manifest, review_text=review_text)
    archive = replace(archive, approvals=(replace(archive.approvals[0], payload_hash=digest(raw)),),
        source_approval_lineage=(replace(archive.source_approval_lineage[0], payload_sha256=digest(raw), bridge=bridge),),
        source_history=replace(archive.source_history, review_bridges=(bridge,),
            source_previews=(replace(record, payload_text=raw, payload_sha256=digest(raw)),)))
    with pytest.raises(rf.Rf1086ArchiveError): rf.serialize_rf1086_archive_v6(archive, query=query(archive))
