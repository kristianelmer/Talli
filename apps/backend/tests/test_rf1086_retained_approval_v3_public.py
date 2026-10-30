"""Public retained v3 composition and exact annual codec, with renderer traps."""
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_source_production_v3 import basis_v3
from test_rf1086_source_readiness_v2 import KINDS
from test_rf1086_retained_readiness_observation_v2 import close_fresh_rendering


def capture(basis):
    text = rf.serialize_rf1086_source_preview(basis.preview)
    return rf.Rf1086ArchiveSourcePreview(basis.preview,text,sha256(text.encode()).hexdigest(),
        str(basis.source.confirmed_by.subject),(basis.source.confirmed_at+timedelta(seconds=1)).isoformat())


@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('depth',[0,1,2])
def test_public_retained_manifest_and_annual_bytes_match_fresh_without_rendering(kind,depth,monkeypatch):
    basis = basis_v3(kind,amendments=depth)
    retained = capture(basis)
    expected = rf.build_rf1086_source_approval_manifest_v3(basis)
    annual_text = rf.serialize_rf1086_annual_readiness_v2(basis.annual_readiness,basis.source,basis.preview)
    close_fresh_rendering(monkeypatch)
    actual = rf.build_rf1086_retained_source_approval_manifest_v3(basis,retained)
    assert actual == expected
    assert rf.serialize_rf1086_source_approval_manifest_v3(actual) == rf.serialize_rf1086_source_approval_manifest_v3(expected)
    rf.assert_rf1086_retained_source_approval_manifest_matches_v3(actual,basis,retained)
    assert rf.serialize_rf1086_retained_annual_readiness_v2(basis.annual_readiness,basis.source,retained) == annual_text


@pytest.mark.parametrize('state,changes',[('ready',{}),('warning',{'period_lock_ids':()}),
    ('blocked',{'has_unpaid_items':True})])
def test_retained_annual_codec_preserves_every_policy_status(state,changes,monkeypatch):
    basis = basis_v3(annual_changes=changes)
    assert basis.annual_readiness.readiness_status == state
    expected = rf.serialize_rf1086_annual_readiness_v2(basis.annual_readiness,basis.source,basis.preview)
    retained = capture(basis)
    close_fresh_rendering(monkeypatch)
    assert rf.serialize_rf1086_retained_annual_readiness_v2(basis.annual_readiness,basis.source,retained) == expected
    if state == 'blocked':
        with pytest.raises(rf.Rf1086ProductionError): rf.build_rf1086_retained_source_approval_manifest_v3(basis,retained)


@pytest.mark.parametrize('field,value',[('payload_text','invalid'),('payload_sha256','f'*64),
    ('created_by','invalid'),('created_at','invalid')])
def test_retained_manifest_and_annual_codec_require_complete_capture(field,value,monkeypatch):
    basis = basis_v3();retained = replace(capture(basis),**{field:value})
    close_fresh_rendering(monkeypatch)
    with pytest.raises(rf.Rf1086ProductionError): rf.build_rf1086_retained_source_approval_manifest_v3(basis,retained)
    with pytest.raises(rf.Rf1086ProductionError):
        rf.serialize_rf1086_retained_annual_readiness_v2(basis.annual_readiness,basis.source,retained)


@pytest.mark.parametrize('field,value',[('proof_sha256','f'*64),('readiness_status','blocked'),
    ('required_warning_codes',('forged',))])
def test_self_inconsistent_annual_proof_cannot_be_encoded(field,value,monkeypatch):
    basis = basis_v3();retained = capture(basis)
    forged = replace(basis.annual_readiness,**{field:value})
    close_fresh_rendering(monkeypatch)
    with pytest.raises(rf.Rf1086ProductionError):
        rf.serialize_rf1086_retained_annual_readiness_v2(forged,basis.source,retained)


def test_different_self_consistent_approval_does_not_match_selected_basis(monkeypatch):
    basis = basis_v3();retained = capture(basis)
    alternate = replace(basis,review_sha256=sha256(b'alternate review').hexdigest())
    assert alternate.review_sha256 != basis.review_sha256
    close_fresh_rendering(monkeypatch)
    forged = rf.build_rf1086_retained_source_approval_manifest_v3(alternate,retained)
    with pytest.raises(rf.Rf1086ProductionError,match='payload_changed'):
        rf.assert_rf1086_retained_source_approval_manifest_matches_v3(forged,basis,retained)
