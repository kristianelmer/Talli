"""Annual approval identity and historical replay; no live authority is granted."""
from dataclasses import replace
from hashlib import sha256
import json
from uuid import uuid4

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_annual_readiness import ready_inputs
from test_rf1086_source_production import manifest_basis
from test_rf1086_source_approval_archive import source_archive, read
from test_rf1086_year_source import ACTOR


def annual_basis(inputs=None, basis=None):
    basis = basis or manifest_basis()
    proof = rf.build_rf1086_annual_readiness(basis.source, basis.preview, inputs or ready_inputs())
    return replace(basis, annual_readiness=proof, acknowledged_warning_codes=proof.required_warning_codes)


def test_original_manifest_and_source_bytes_keep_their_recorded_v1_identity():
    # Recorded from the committed V1 implementation before introducing V2.
    basis = manifest_basis()
    assert rf.build_rf1086_source_approval_manifest(basis).manifest_sha256 == (
        'dfb11c2e1d8307320a631b87da661427298d3f9820335c94882abef25fc97a68')
    assert sha256(rf.serialize_rf1086_year_source(basis.source).encode()).hexdigest() == (
        'bcb03d013385f22884a80cb73e9b850999e060a103aaada809d973c2479b3d56')


def test_annual_proof_round_trip_retains_immutable_full_evidence():
    basis = annual_basis(replace(ready_inputs(), period_lock_ids=()))
    text = rf.serialize_rf1086_annual_readiness(basis.annual_readiness, basis.source, basis.preview)
    parsed = rf.parse_rf1086_annual_readiness(text, basis.source, basis.preview)
    assert parsed == basis.annual_readiness
    assert parsed.required_warning_codes == ('period_not_locked',)
    with pytest.raises(TypeError): parsed.annual_inputs.evidence_sha256['ledger'] = 'b' * 64


@pytest.mark.parametrize('change', ['extra', 'duplicate', 'space', 'version', 'status', 'digest',
                                  'scope', 'unknown_record', 'missing_field', 'omissions', 'preview'])
def test_changed_or_noncanonical_retained_proof_is_rejected(change):
    basis = annual_basis()
    text = rf.serialize_rf1086_annual_readiness(basis.annual_readiness, basis.source, basis.preview)
    raw = json.loads(text)
    if change == 'extra': raw['extra'] = True
    if change == 'version': raw['codec'] = 'rf1086-annual-readiness-v99'
    if change == 'status': raw['proof']['fields']['readiness_status'] = 'blocked'
    if change == 'digest': raw['proof']['fields']['proof_sha256'] = 'b' * 64
    if change == 'scope':
        raw['proof']['fields']['annual_inputs']['fields']['company_id']['fields']['value'] = str(uuid4())
    if change == 'unknown_record': raw['proof']['record'] = 'ExecutableType'
    if change == 'missing_field': del raw['proof']['fields']['issues']
    if change == 'omissions': raw['proof']['fields']['not_evaluated'] = []
    text = json.dumps(raw, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    if change == 'duplicate': text = text.replace('"codec":', '"codec":"ignored","codec":', 1)
    if change == 'space': text += ' '
    preview = basis.preview
    if change == 'preview': preview = replace(preview, preview_id=rf.PreviewId(str(uuid4())))
    with pytest.raises(rf.Rf1086ProductionError):
        rf.parse_rf1086_annual_readiness(text, basis.source, preview)


def test_same_payload_changed_annual_metadata_changes_approval_identity():
    basis = annual_basis()
    approved = rf.build_rf1086_source_approval_manifest(basis)
    inputs = basis.annual_readiness.annual_inputs
    changed = annual_basis(replace(inputs, evidence_sha256=dict(inputs.evidence_sha256) | {'ledger': 'b'*64}))
    other = rf.build_rf1086_source_approval_manifest(changed)
    assert approved.manifest['schemaVersion'] == 'production-source-approval-v2'
    assert approved.document_order == other.document_order
    assert approved.underskjema_xml == other.underskjema_xml
    assert approved.manifest['documentHashes'] == other.manifest['documentHashes']
    assert approved.manifest_sha256 != other.manifest_sha256
    with pytest.raises(rf.Rf1086ProductionError):
        rf.assert_rf1086_source_approval_manifest_matches(approved, changed)


@pytest.mark.parametrize('change', ['blocked', 'unacknowledged', 'extra_acknowledgement', 'forged'])
def test_annual_conditions_cannot_be_bypassed_by_ready_source_preview(change):
    inputs = replace(ready_inputs(), period_lock_ids=())
    if change == 'blocked': inputs = replace(inputs, has_unpaid_items=True)
    basis = annual_basis(inputs)
    if change == 'unacknowledged': basis = replace(basis, acknowledged_warning_codes=())
    if change == 'extra_acknowledgement': basis = replace(basis, acknowledged_warning_codes=('unknown',))
    if change == 'forged': basis = replace(basis, annual_readiness=replace(basis.annual_readiness, issues=()))
    assert basis.preview.readiness_status == 'ready'
    with pytest.raises(rf.Rf1086ProductionError): rf.build_rf1086_source_approval_manifest(basis)


def annual_archive():
    snapshot = source_archive()
    line, approval = snapshot.source_approval_lineage[0], snapshot.approvals[0]
    basis = annual_basis(replace(ready_inputs(), period_lock_ids=()), basis=rf.Rf1086SourceApprovalManifestBasis(
        line.source, line.source_preview, ACTOR, approval.entitlement_id, line.review_sha256, ()))
    draft = rf.build_rf1086_source_approval_manifest(basis)
    review = json.loads(line.review_text)
    review.pop('storedReleaseReady')
    review.update(version='rf1086-source-review-v2', otherOverridesReady=True,
                  annualReadiness=dict(draft.manifest['annualReadiness']))
    review['scope']['warningCodes'] = list(basis.acknowledged_warning_codes)
    return rewrite_archive(snapshot, review, basis)


def rewrite_archive(snapshot, review, basis):
    line, approval = snapshot.source_approval_lineage[0], snapshot.approvals[0]
    text = json.dumps(review, sort_keys=True, ensure_ascii=False)
    digest = sha256(text.encode()).hexdigest()
    manifest = rf.build_rf1086_source_approval_manifest(replace(basis, review_sha256=digest))
    return replace(snapshot,
        approvals=(replace(approval, manifest=manifest.manifest, manifest_hash=manifest.manifest_sha256),),
        source_approval_lineage=(replace(line, review_text=text, review_sha256=digest,
            manifest_text=rf.serialize_rf1086_source_approval_manifest(manifest),
            manifest_sha256=manifest.manifest_sha256),))


def test_annual_archive_rebuilds_retained_policy_without_reading_current_facts():
    snapshot = annual_archive()
    assert read(snapshot) is snapshot
    line, approval = snapshot.source_approval_lineage[0], snapshot.approvals[0]
    retained = rf.Rf1086RetainedSourceApproval(approval, line.manifest_text)
    assert rf.inspect_rf1086_retained_source_approval(retained, approval_id=rf.ApprovalId(approval.id),
        manifest_sha256=approval.manifest_hash, actor_id=ACTOR) is None


@pytest.mark.parametrize('change', ['v1_review', 'other_override', 'technical', 'different_proof', 'extra'])
def test_rehashed_review_cannot_weaken_annual_archive_release_evidence(change):
    snapshot = annual_archive()
    line, approval = snapshot.source_approval_lineage[0], snapshot.approvals[0]
    review = json.loads(line.review_text)
    proof = rf.parse_rf1086_annual_readiness(approval.manifest['annualReadiness']['proofText'],
                                            line.source, line.source_preview)
    basis = rf.Rf1086SourceApprovalManifestBasis(line.source, line.source_preview, ACTOR,
        approval.entitlement_id, line.review_sha256, proof.required_warning_codes, annual_readiness=proof)
    if change == 'v1_review':
        review.pop('annualReadiness'); review.pop('otherOverridesReady')
        review.update(version='rf1086-source-review-v1', storedReleaseReady=True)
    if change == 'other_override': review['otherOverridesReady'] = False
    if change == 'technical': review['technicalReleaseReady'] = False
    if change == 'different_proof': review['annualReadiness']['proofSha256'] = 'b' * 64
    if change == 'extra': review['extra'] = True
    with pytest.raises(rf.ShareholderRegisterFilingError): read(rewrite_archive(snapshot, review, basis))


@pytest.mark.parametrize('change', ['text_hash', 'policy_hash', 'unknown_version', 'extra', 'downgrade'])
def test_rehashed_manifest_cannot_publish_damaged_annual_binding(change):
    snapshot = annual_archive()
    line, approval = snapshot.source_approval_lineage[0], snapshot.approvals[0]
    manifest = json.loads(line.manifest_text)
    binding = manifest['annualReadiness']
    if change == 'text_hash': binding['proofTextSha256'] = 'b' * 64
    if change == 'policy_hash': binding['proofSha256'] = 'b' * 64
    if change == 'unknown_version': binding['schemaVersion'] = 'unknown'
    if change == 'extra': binding['extra'] = True
    if change == 'downgrade': manifest['schemaVersion'] = 'production-source-approval-v1'
    text = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    digest = sha256(text.encode()).hexdigest()
    with pytest.raises(rf.ShareholderRegisterFilingError):
        read(replace(snapshot, approvals=(replace(approval, manifest=manifest, manifest_hash=digest),),
            source_approval_lineage=(replace(line, manifest_text=text, manifest_sha256=digest),)))


def test_unclaimed_v1_requires_fresh_annual_approval_but_exact_historical_claim_recovers():
    from test_rf1086_source_claim import ClaimHarness
    c = ClaimHarness()
    h, approval = c.h, c.retained.approval
    basis = rf.Rf1086SourceApprovalManifestBasis(h.source, h.preview, h.actor,
        approval.entitlement_id, h.review.review_sha256, h.review.warning_codes)
    manifest = rf.build_rf1086_source_approval_manifest(basis)
    c.retained = rf.Rf1086RetainedSourceApproval(replace(approval,
        manifest=manifest.manifest, manifest_hash=manifest.manifest_sha256),
        rf.serialize_rf1086_source_approval_manifest(manifest))
    c.locked_retained = c.retained
    c.manifest_sha256 = manifest.manifest_sha256
    with pytest.raises(rf.Rf1086ProductionError): c.run()
    assert 'claim' not in h.calls and not h.committed
    # A previously committed exact claim still recovers with no current inputs.
    c.claim = replace(c.claim, manifest_sha256=manifest.manifest_sha256)
    c.existing = c.claim
    c.retained = None
    h.calls.clear()
    result = c.run()
    assert result.claim == c.claim and not result.newly_claimed
    assert h.calls == ['recover']
