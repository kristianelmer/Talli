"""Independent live correction boundaries; synthetic ports, real retained proof."""
import asyncio
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from rf1086_retained_correction_fixture import RetainedCorrectionHarness, correction_fixture
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, UserId


PROFILES = ('legacy-no-activity', 'source-v1', 'source-v3')


def harness(profile='source-v1', *, bound=True):
    return RetainedCorrectionHarness(correction_fixture(profile,
        'cash_issue' if profile == 'source-v3' else 'formation',
        amendments=2 if profile == 'source-v3' else 0, bound_feedback=bound))


def owner_project(h, archive):
    return rf.prepare_rf1086_retained_correction_predecessor(archive,
        query=rf.Rf1086ArchiveQuery(archive.company_id, archive.income_year, h.actor),
        predecessor=h.prior)


def selected_source(h):
    return h.prior_snapshot.source_approval_lineage.source


def capture_change(archive, source_id, **changes):
    history = archive.source_history
    return replace(archive, source_history=replace(history, source_capture_records=tuple(
        replace(row, **changes) if row.record_id == source_id.value else row
        for row in history.source_capture_records)))


def assert_denied(h, phase, mutate):
    if phase == 'preflight':
        h.archive = mutate(h.archive)
        action = h.prepare()
    else:
        verified = asyncio.run(h.prepare())
        h.calls.clear()
        h.locked_archive = mutate(h.locked_archive)
        action = h.check_held(verified)
    with pytest.raises(rf.Rf1086ProductionError, match='^basis_unavailable$'):
        asyncio.run(action)
    assert not h.writes and not h.held and not h.committed
    if phase == 'preflight':
        assert h.calls == ['retained_prior_read']
    else:
        assert h.calls == ['guard', 'retained_prior_lock', 'release']


@pytest.mark.parametrize('profile', PROFILES)
@pytest.mark.parametrize('phase', ['preflight', 'held'])
@pytest.mark.parametrize('field', ['source_history', 'overrides', 'withdrawal_capture_records'])
def test_live_reads_require_every_capture_section_even_for_legacy(profile, phase, field):
    h = harness(profile)
    assert_denied(h, phase, lambda archive: replace(archive, **{field: None}))


@pytest.mark.parametrize('phase', ['preflight', 'held'])
@pytest.mark.parametrize('field', ['source_history', 'overrides', 'withdrawal_capture_records'])
def test_complete_section_types_are_not_duck_typed(phase, field):
    h = harness('legacy-no-activity')
    invalid = (SimpleNamespace(**{item.name: getattr(h.archive.source_history, item.name)
                                  for item in fields(h.archive.source_history)})
               if field == 'source_history' else {})
    assert_denied(h, phase, lambda archive: replace(archive, **{field: invalid}))


@pytest.mark.parametrize('profile', ['source-v1', 'source-v3'])
@pytest.mark.parametrize('phase', ['preflight', 'held'])
def test_live_full_year_cannot_omit_selected_source_capture(profile, phase):
    h = harness(profile)
    identity = selected_source(h).source_id.value
    def missing(archive):
        history = archive.source_history
        return replace(archive, source_history=replace(history, source_capture_records=tuple(
            row for row in history.source_capture_records if row.record_id != identity)))
    assert_denied(h, phase, missing)


@pytest.mark.parametrize('profile', ['source-v1', 'source-v3'])
@pytest.mark.parametrize('field', ['source-envelope', 'source-key', 'preview-capture-time'])
def test_equal_compact_parent_cannot_hide_changed_selected_raw_capture(profile, field):
    h = harness(profile)
    verified = asyncio.run(h.prepare())
    source = selected_source(h)
    if field == 'preview-capture-time':
        history = h.locked_archive.source_history
        preview_id = h.prior_snapshot.source_approval_lineage.source_preview.preview_id
        h.locked_archive = replace(h.locked_archive, source_history=replace(history,
            source_previews=tuple(replace(row, created_at=datetime.fromisoformat(row.created_at)
                .astimezone(timezone(timedelta(hours=1))).isoformat())
                if row.preview.preview_id == preview_id else row for row in history.source_previews)))
    else:
        row = next(row for row in h.locked_archive.source_history.source_capture_records
                   if row.record_id == source.source_id.value)
        changes = ({'snapshot_text': json.dumps(json.loads(row.snapshot_text), indent=2)}
                   if field == 'source-envelope' else {'idempotency_key': 'independent-selected-key-0001'})
        h.locked_archive = capture_change(h.locked_archive, source.source_id, **changes)
    # Both complete archives pass owner policy; dataclass parent equality cannot
    # express the selected original recovery-envelope identity.
    assert owner_project(h, h.locked_archive) == verified.snapshot
    assert h.locked_snapshot == verified.snapshot
    h.calls.clear()
    with pytest.raises(rf.Rf1086ProductionError, match='^basis_unavailable$'):
        asyncio.run(h.check_held(verified))
    assert h.calls == ['guard', 'retained_prior_lock', 'release']
    assert not h.writes and not h.held and not h.committed


@pytest.mark.parametrize('profile', ['source-v1', 'source-v3'])
def test_matching_noncanonical_selected_capture_is_preserved(profile):
    h = harness(profile)
    source = selected_source(h)
    row = next(row for row in h.archive.source_history.source_capture_records
               if row.record_id == source.source_id.value)
    text = json.dumps(json.loads(row.snapshot_text), indent=2)
    assert text != row.snapshot_text
    h.archive = h.locked_archive = capture_change(h.archive, source.source_id,
        snapshot_text=text, idempotency_key='matching-selected-original-0001')
    verified = asyncio.run(h.prepare())
    asyncio.run(h.check_held(verified))
    assert h.calls.count('historical_original') == 2
    assert next(row for row in h.archive.source_history.source_capture_records
        if row.record_id == source.source_id.value).snapshot_text == text
    assert not h.writes and not h.held


@pytest.mark.parametrize('field', ['source-envelope', 'source-key'])
def test_valid_nonselected_child_capture_change_is_not_whole_archive_drift(field):
    h = harness()
    verified = asyncio.run(h.prepare())
    assert h.source.source_id != selected_source(h).source_id
    row = next(row for row in h.locked_archive.source_history.source_capture_records
               if row.record_id == h.source.source_id.value)
    changes = ({'snapshot_text': json.dumps(json.loads(row.snapshot_text), indent=2)}
               if field == 'source-envelope' else {'idempotency_key': 'unrelated-child-new-key-0001'})
    h.locked_archive = capture_change(h.locked_archive, h.source.source_id, **changes)
    assert h.locked_archive != h.archive
    assert owner_project(h, h.locked_archive) == verified.snapshot
    asyncio.run(h.check_held(verified))
    assert not h.writes and not h.held


@pytest.mark.parametrize('phase', ['preflight', 'held'])
def test_invalid_unselected_history_is_validated_before_feedback(phase):
    h = harness()
    assert h.source.source_id != selected_source(h).source_id
    assert_denied(h, phase, lambda archive: capture_change(archive,
        h.source.source_id, request_sha256='f' * 64))


@pytest.mark.parametrize('shape', ['duck-actor', 'actor-subclass', 'string-subject', 'foreign-owner'])
def test_exact_original_actor_is_required_before_documents(shape):
    h = harness('source-v3')
    class ActorSubclass(ActorId):
        pass
    actors = {'duck-actor': SimpleNamespace(kind=ActorKind.USER, subject=h.actor.subject),
        'actor-subclass': ActorSubclass(ActorKind.USER, h.actor.subject),
        'string-subject': ActorId(ActorKind.USER, str(h.actor.subject)),
        'foreign-owner': ActorId(ActorKind.USER, UserId('aaaa0000-0000-4000-8000-000000000002'))}
    h.actor = actors[shape]
    error = rf.ShareholderRegisterFilingError if shape == 'duck-actor' else rf.Rf1086ProductionError
    message = '^SHAREHOLDER_REGISTER_FILING_INVALID_INPUT$' if shape == 'duck-actor' else '^basis_unavailable$'
    with pytest.raises(error, match=message):
        asyncio.run(h.prepare())
    assert h.calls == ['retained_prior_read'] and not h.writes and not h.held


@pytest.mark.parametrize('profile', PROFILES)
def test_helper_checks_only_feedback_bytes_without_fresh_or_whole_archive_builders(profile, monkeypatch):
    h = harness(profile)
    def forbidden(*args, **kwargs):
        raise AssertionError('Correction must use retained proof, not fresh builders or whole-archive encoding')
    for name in ('prepare_rf1086_year_source', 'prepare_rf1086_year_source_v2',
                 'render_rf1086_preview', 'assert_rf1086_source_preview_matches',
                 'build_rf1086_source_approval_manifest',
                 'serialize_rf1086_archive', 'serialize_rf1086_archive_v6'):
        monkeypatch.setattr(rf, name, forbidden)
    # A v2 integrity check legitimately invokes the frozen v1 business validator;
    # do not forbid that pure owner validation as though it were fresh admission.
    verified = asyncio.run(h.prepare())
    asyncio.run(h.check_held(verified))
    reads = [call.split(':', 1)[1] for call in h.calls if call.startswith('historical_bytes:')]
    assert set(reads) == h.feedback_ids and len(reads) == len(h.feedback_ids) == 2
    assert 'prior_read' not in h.calls and 'prior_lock' not in h.calls
    assert h.calls.count('historical_original') == 2 and not h.held and not h.writes


@pytest.mark.parametrize('phase', ['documents', 'held-read', 'held-original'])
def test_cancellation_propagates_without_effect_and_releases_owned_scope(phase):
    h = harness('source-v3')
    if phase == 'documents':
        h.prior_failure = asyncio.CancelledError('cancel feedback')
        action = h.prepare()
    else:
        verified = asyncio.run(h.prepare())
        h.calls.clear()
        async def cancel(*args):
            h.calls.append('cancelled-operation')
            raise asyncio.CancelledError('cancel held read')
        setattr(h.transaction, 'read_retained_correction_archive' if phase == 'held-read'
                else 'assert_historical_original', cancel)
        action = h.check_held(verified)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(action)
    assert not h.writes and not h.held and not h.committed
    if phase == 'documents':
        assert 'guard' not in h.calls
    else:
        assert h.calls[-1] == 'release'


@pytest.mark.parametrize('same_before', [False, True])
def test_equal_decimal_scale_in_selected_source_is_bound_as_owner_wire(same_before):
    h = harness('source-v3')
    source = selected_source(h)
    paid = replace(source.command.paid_in,
        opening_capital=Decimal(source.command.paid_in.opening_capital).quantize(Decimal('0.00')))
    changed = replace(source, command=replace(source.command, paid_in=paid))
    assert source == changed
    text = rf.serialize_rf1086_year_source_v2(changed)
    assert text != rf.serialize_rf1086_year_source_v2(source)
    archive = h.locked_archive
    archive = replace(archive, source_history=replace(archive.source_history,
        year_sources=tuple(changed if row.source_id == source.source_id else row
                           for row in archive.source_history.year_sources)),
        source_approval_lineage=tuple(replace(line, source=changed)
            if line.source.source_id == source.source_id else line for line in archive.source_approval_lineage))
    archive = capture_change(archive, source.source_id, snapshot_text=text)
    assert owner_project(h, archive) == h.prior_snapshot
    if same_before:
        h.archive = archive
    verified = asyncio.run(h.prepare())
    h.locked_archive = archive
    h.calls.clear()
    if same_before:
        asyncio.run(h.check_held(verified))
        assert h.calls.count('historical_original') == 2
    else:
        with pytest.raises(rf.Rf1086ProductionError, match='^basis_unavailable$'):
            asyncio.run(h.check_held(verified))
        assert h.calls == ['guard', 'retained_prior_lock', 'release']
    assert not h.writes and not h.held
