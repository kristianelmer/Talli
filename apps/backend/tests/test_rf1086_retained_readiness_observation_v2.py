"""Public saved observations: exact correspondence, no live authority or renderer."""
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_source_readiness_v2 import KINDS, source_and_preview
from test_rf1086_annual_readiness_v2 import inputs_for


def capture(source, preview):
    text = rf.serialize_rf1086_source_preview(preview)
    return rf.Rf1086ArchiveSourcePreview(preview, text, sha256(text.encode()).hexdigest(),
        str(source.confirmed_by.subject), source.confirmed_at.isoformat())


def fail_renderer(*args, **kwargs):
    raise AssertionError('retained observation called fresh renderer/builder')


def close_fresh_rendering(monkeypatch):
    from talli_backend.modules.shareholder_register_filing import source_preview
    monkeypatch.setattr(source_preview, 'render_rf1086_preview', fail_renderer)
    for name in ('render_rf1086_preview', 'assert_rf1086_source_preview_matches',
            'build_rf1086_source_readiness_v2', 'build_rf1086_annual_readiness_v2'):
        monkeypatch.setattr(rf, name, fail_renderer)


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('amendments', [0, 1, 2])
def test_retained_public_builders_preserve_fresh_policy_and_saved_bytes_without_renderer(kind, amendments, monkeypatch):
    source, preview = source_and_preview(kind, amendments=amendments)
    retained = capture(source, preview)
    inputs = inputs_for(source)
    expected_source = rf.build_rf1086_source_readiness_v2(source, preview)
    expected_annual = rf.build_rf1086_annual_readiness_v2(source, preview, inputs)
    wire = rf.serialize_rf1086_year_source_v2(source)
    close_fresh_rendering(monkeypatch)
    assert rf.build_rf1086_retained_source_readiness_v2(source, retained) == expected_source
    assert rf.build_rf1086_retained_annual_readiness_v2(source, retained, inputs) == expected_annual
    assert retained.payload_text == rf.serialize_rf1086_source_preview(preview)
    assert rf.serialize_rf1086_year_source_v2(source) == wire
    assert expected_source.not_evaluated == ('annual_prerequisites', 'current_review_comments', 'filing_overrides',
        'authority_permission', 'billing_entitlement', 'technical_release', 'warning_acknowledgements')


@pytest.mark.parametrize('field,value',[('payload_text','truncated'),('payload_sha256','f'*64),
    ('created_by','not-a-user'),('created_at','not-a-time'),('created_at','2020-01-01T00:00:00'),
    ('preview',None)])
def test_malformed_retained_capture_is_rejected_without_fresh_rendering(field,value,monkeypatch):
    source, preview = source_and_preview()
    retained = replace(capture(source, preview), **{field:value})
    close_fresh_rendering(monkeypatch)
    with pytest.raises(rf.Rf1086ProductionError,match='basis_unavailable'):
        rf.build_rf1086_retained_source_readiness_v2(source,retained)
    with pytest.raises(rf.Rf1086ProductionError,match='basis_unavailable'):
        rf.build_rf1086_retained_annual_readiness_v2(source,retained,inputs_for(source))


def test_saved_preview_cannot_predate_its_source(monkeypatch):
    source, preview = source_and_preview()
    retained = replace(capture(source,preview),created_at=(source.confirmed_at-timedelta(seconds=1)).isoformat())
    close_fresh_rendering(monkeypatch)
    with pytest.raises(rf.Rf1086ProductionError,match='basis_unavailable'):
        rf.build_rf1086_retained_source_readiness_v2(source,retained)


@pytest.mark.parametrize('change',['ready','warning','blocked','missing_interview'])
def test_retained_annual_observation_keeps_all_policy_dispositions(change,monkeypatch):
    source, preview = source_and_preview('no_activity',amendments=0)
    inputs = replace(inputs_for(source),accepted_bank_warning_count=0)
    if change=='warning':inputs=replace(inputs,period_lock_ids=())
    if change=='blocked':inputs=replace(inputs,unmatched_bank_count=1)
    if change=='missing_interview':inputs=replace(inputs,interview_source_id=None,
        bank_balance_confirmed=None,has_unpaid_items=None,authority_to_submit_confirmed=None)
    expected=rf.build_rf1086_annual_readiness_v2(source,preview,inputs)
    retained=capture(source,preview);close_fresh_rendering(monkeypatch)
    result=rf.build_rf1086_retained_annual_readiness_v2(source,retained,inputs)
    assert result==expected
    assert result.readiness_status==('warning' if change=='missing_interview' else change)


def test_retained_blocked_preview_is_observed_as_saved_instead_of_recreated(monkeypatch):
    source, preview=source_and_preview('no_activity',amendments=0)
    preview=replace(preview,readiness_status='blocked',hovedskjema_xml=None,underskjema_xml=None,
        readiness_issues=(rf.Rf1086ReadinessIssue('error','retained_test_blocker','Saved blocked rendering'),))
    retained=capture(source,preview);close_fresh_rendering(monkeypatch)
    result=rf.build_rf1086_retained_source_readiness_v2(source,retained)
    assert result.readiness_status=='blocked' and result.issues==preview.readiness_issues
    assert rf.build_rf1086_retained_annual_readiness_v2(source,retained,inputs_for(source)).readiness_status=='blocked'
