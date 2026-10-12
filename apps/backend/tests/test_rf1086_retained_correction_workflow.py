"""Retained correction application checks; no SQL or v3 writer activation."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from uuid import UUID

import pytest

from talli_backend.modules.documents import public as documents
from talli_backend.modules.shareholder_register_filing import public as rf
from rf1086_retained_correction_fixture import (
    RetainedCorrectionHarness, correction_fixture, selected_snapshot,
)


LEGACY = [('legacy-no-activity', 'no_activity'), ('source-v1', 'no_activity'),
          ('source-v1', 'formation'), ('source-v1', 'dividend')]


@pytest.mark.parametrize('profile,kind', LEGACY)
@pytest.mark.parametrize('status', ['accepted', 'rejected'])
@pytest.mark.parametrize('bound', [False, True])
def test_complete_legacy_fixture_passes_owner_and_retained_helper(profile, kind, status, bound):
    fixture = correction_fixture(profile, kind, status, bound_feedback=bound)
    h = RetainedCorrectionHarness(fixture)
    verified = asyncio.run(h.prepare())
    assert verified.snapshot == selected_snapshot(h.archive, h.prior.submission_id)
    assert len(verified.originals) == len(verified.snapshot.artifacts) == 2
    assert type(h.archive.source_history) is rf.Rf1086ArchiveSourceHistory
    assert h.archive.overrides == h.archive.withdrawal_capture_records == ()
    for receipt in verified.originals:
        query = documents.RetainedDocumentOriginalQuery(receipt.document_id, receipt.company_id,
            receipt.source_income_year, receipt.metadata_sha256, receipt.content_sha256, receipt.byte_length)
        value = h.originals[query]
        assert receipt == value.original.receipt
        assert sha256(value.original.content).hexdigest() == receipt.content_sha256
    asyncio.run(h.check_held(verified))
    prefix = 'historical_bytes:' if bound else 'prior_bytes:'
    assert all(h.calls.index(call) < h.calls.index('guard') for call in h.calls if call.startswith(prefix))
    assert h.calls.index('retained_prior_lock') < h.calls.index('historical_original' if bound else 'prior_original')
    assert not h.held and not h.writes


@pytest.mark.parametrize('profile,kind', LEGACY)
@pytest.mark.parametrize('status', ['accepted', 'rejected'])
@pytest.mark.parametrize('bound', [False, True])
def test_unchanged_outer_approval_and_claim_use_same_selected_originals(profile, kind, status, bound):
    h = RetainedCorrectionHarness(correction_fixture(profile, kind, status, bound_feedback=bound))
    result = h.approve(predecessor=h.prior)
    assert result == h.result and h.committed and not h.held
    text = rf.serialize_rf1086_source_approval_manifest(h.writes[-1])
    assert dict(h.writes[-1].manifest['predecessor']) == {
        'submissionId': h.prior.submission_id.value,
        'manifestSha256': h.prior.manifest_sha256, 'reason': h.prior.reason}
    assert h.calls.index('retained_prior_read') < h.calls.index('guard') < h.calls.index('retained_prior_lock') < h.calls.index('append')
    claim = h.make_claim_workflow()
    assert claim.retained.manifest_text == text
    assert claim.run() == claim.result and h.committed and not h.held
    assert h.calls.index('recover') < h.calls.index('retained_prior_read') < h.calls.index('guard')
    assert h.calls.index('locked_recover') < h.calls.index('retained_prior_lock') < h.calls.index('claim')
    assert claim.result.claim.predecessor_submission_id == h.prior.submission_id


@pytest.mark.parametrize('kind', ['cash_issue', 'loss_covering_reduction'])
@pytest.mark.parametrize('amendments', [0, 1, 2])
@pytest.mark.parametrize('status', ['accepted', 'rejected'])
def test_v3_valid_retained_parent_passes_both_actual_retained_reads(kind, amendments, status, monkeypatch):
    fixture = correction_fixture('source-v3', kind, status, amendments)
    source = fixture.archive.source_approval_lineage[0].source
    assert len(source.governance_projection.chains) == 1
    assert source.governance_projection.chains[0].amendment_count == amendments
    assert len(fixture.archive.source_history.register_observations) == amendments + 1
    assert len(fixture.archive.withdrawal_capture_records) == amendments
    h = RetainedCorrectionHarness(fixture)
    def forbidden(*args, **kwargs):
        raise AssertionError('Retained ancestry must not invoke the old validator or renderer')
    monkeypatch.setattr(rf, 'assert_rf1086_correction_predecessor', forbidden)
    monkeypatch.setattr(rf, 'render_rf1086_preview', forbidden)
    verified = asyncio.run(h.prepare())
    assert verified.snapshot == h.prior_snapshot
    assert len(verified.originals) == len(h.prior_snapshot.artifacts) == 2
    asyncio.run(h.check_held(verified))
    assert h.calls[0] == 'retained_prior_read'
    assert h.calls.index('retained_prior_lock') < h.calls.index('historical_original')
    assert not h.writes and not h.held
    assert all(call.split(':', 1)[1] in h.feedback_ids
        for call in h.calls if call.startswith(('prior_bytes:', 'historical_bytes:')))
    # Actual v2/v3 retained ancestry is usable; fresh v2 child admission is closed.



@pytest.mark.parametrize('bound', [False, True])
@pytest.mark.parametrize('mutation', ['bytes', 'metadata', 'receipt', 'owner'])
def test_existing_feedback_failure_semantics_precede_guard(bound, mutation):
    h = RetainedCorrectionHarness(correction_fixture(bound_feedback=bound))
    if mutation == 'owner':
        h.document_actor = replace(h.actor, subject=type(h.actor.subject)('00000000-0000-0000-0000-000000088888'))
    elif not bound:
        key = sorted(h.prior_documents)[0]
        item = h.prior_documents[key]
        if mutation == 'bytes': h.prior_failure = documents.DocumentsError.integrity_failed()
        if mutation == 'metadata': h.prior_documents[key] = replace(item, document=replace(item.document, name='changed'))
        if mutation == 'receipt': h.prior_documents[key] = replace(item, retained_original=None)
    else:
        artifact = h.prior_snapshot.artifacts[0]
        key = next(q for q in h.originals if q.document_id.value == artifact.document_id)
        item = h.originals[key]
        if mutation == 'bytes': item = replace(item, original=replace(item.original, content=b'changed'))
        if mutation == 'metadata': item = replace(item, document=replace(item.document, name='changed'))
        if mutation == 'receipt': item = replace(item, original=replace(item.original,
            receipt=replace(item.original.receipt, original_id='00000000-0000-0000-0000-000000088888')))
        h.originals[key] = item
    with pytest.raises((rf.Rf1086ProductionError, documents.DocumentsError)):
        asyncio.run(h.prepare())
    assert 'guard' not in h.calls and not h.writes and not h.held


@pytest.mark.parametrize('bound', [False, True])
def test_changed_selected_parent_is_rejected_inside_unchanged_held_scope(bound):
    h = RetainedCorrectionHarness(correction_fixture(bound_feedback=bound))
    verified = asyncio.run(h.prepare())
    row = h.locked_archive.production_submissions[0]
    h.locked_archive = replace(h.locked_archive,
        production_submissions=(replace(row, updated_at='2026-01-11T00:00:00+00:00'),))
    with pytest.raises(rf.Rf1086ProductionError, match='^basis_unavailable$'):
        asyncio.run(h.check_held(verified))
    assert h.calls[-1] == 'release' and not h.held and not h.committed and not h.writes


def test_exact_committed_claim_recovers_before_any_parent_or_documents_read():
    h = RetainedCorrectionHarness(correction_fixture())
    claim = h.make_claim_workflow()
    claim.existing = claim.claim
    h.prior_failure = AssertionError('Committed claim must not read Documents')
    assert claim.run() == rf.Rf1086SourceSubmissionClaimResult(claim.claim, False)
    assert h.calls == ['recover'] and not h.held and not h.writes


@pytest.mark.parametrize('profile,kind', LEGACY)
def test_outer_archive_contains_current_unapproved_then_approved_child(profile, kind):
    h = RetainedCorrectionHarness(correction_fixture(profile, kind))
    parent = h.prior_snapshot
    history = h.archive.source_history
    expected_count = 1 if profile == 'legacy-no-activity' else 2
    assert len(history.year_sources) == len(history.source_capture_records) == expected_count
    assert history.year_sources[-1] is h.source
    assert history.year_source_head.source_id == h.source.source_id
    assert history.year_source_head.version == h.source.version == expected_count
    assert history.source_previews[-1].preview is h.preview
    assert history.source_previews[-1].payload_text == rf.serialize_rf1086_source_preview(h.preview)
    assert history.review_bridges[-1] == h.child_bridge
    assert any(row.id == h.preview.preview_id.value for row in h.archive.previews)
    assert all(row.preview_id != h.preview.preview_id.value for row in h.archive.approvals)
    h.assert_complete_archive()
    assert h.prior_snapshot == parent
    if parent.source_approval_lineage is not None:
        assert h.source.command.supersedes_source_id == parent.source_approval_lineage.source.source_id
        assert h.source.command.supersedes_source_sha256 == parent.source_approval_lineage.source.source_sha256
    claim = h.make_claim_workflow()
    line = next(row for row in h.archive.source_approval_lineage if row.approval_id == claim.approval_id.value)
    assert line.source is h.source and line.source_preview is h.preview
    assert line.manifest_text == claim.retained.manifest_text
    assert line.review_text == h.child_review_text
    assert claim.retained.approval in h.archive.approvals
    assert claim.retained.approval in h.locked_archive.approvals
    h.assert_complete_archive()
    assert h.prior_snapshot == parent
    assert claim.run() == claim.result


def test_v3_fixture_does_not_invent_a_fresh_v1_child_after_v2():
    h = RetainedCorrectionHarness(correction_fixture('source-v3', 'cash_issue'))
    assert not h.outer_supported
    assert h.archive is h.fixture.archive
    with pytest.raises(ValueError, match='fresh v2 child writer remains closed'):
        h.approve(predecessor=h.prior)
    assert not h.calls and not h.writes


def test_new_unapproved_source_after_preflight_preserves_selected_ancestry():
    from test_rf1086_archive_history import with_captures

    h = RetainedCorrectionHarness(correction_fixture('source-v1', 'formation'))
    verified = asyncio.run(h.prepare())
    previous = h.archive.source_history.year_sources[-1]
    command = replace(previous.command, supersedes_source_id=previous.source_id,
        supersedes_source_sha256=previous.source_sha256,
        correction_reason='Unapproved source extension after preflight')
    source = rf.prepare_rf1086_year_source(command, context=h.source_harness.context,
        previous=previous, source_id=rf.Rf1086YearSourceId(str(UUID(int=88501))),
        confirmed_at=previous.confirmed_at + timedelta(seconds=1))
    history = with_captures(replace(h.archive.source_history,
        year_sources=h.archive.source_history.year_sources + (source,),
        year_source_head=rf.Rf1086ArchiveYearSourceHead(source.company_id,
            source.income_year, source.source_id, source.version, source.source_sha256)))
    h.locked_archive = replace(h.archive, source_history=history)
    assert h.locked_archive != h.archive
    assert source.version == 3
    assert rf.prepare_rf1086_retained_correction_predecessor(h.locked_archive,
        query=h.fixture.query, predecessor=h.prior) == verified.snapshot
    h.calls.clear()
    asyncio.run(h.check_held(verified))
    assert h.calls.count('historical_original') == 2
    assert h.calls[0] == 'guard' and h.calls[-1] == 'release'
    assert not h.writes and not h.held
