"""Retained manifest composition preserves released bytes without fresh admission."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.modules.shareholder_register_filing import retained_readiness as readiness
from talli_backend.modules.shareholder_register_filing import retained_source_approval as retained
from test_rf1086_annual_readiness_v2 import inputs_for, uid
from test_rf1086_source_preview import preview_source
from test_rf1086_source_production import manifest_basis
from test_rf1086_source_production_v3 import basis_v3
from test_rf1086_source_readiness_v2 import KINDS


GOLDENS = json.loads((Path(__file__).parent / 'fixtures/rf1086_year_source_v1_pre_v2.json').read_text())['vectors']


def commitment(preview, raw=True):
    text = rf.serialize_rf1086_source_preview(preview)
    return dict(preview_payload_sha256=sha256(text.encode()).hexdigest(),
                preview_payload_text=text if raw else None)


def legacy(fixture, *, annual=False, changes=None):
    source = rf.parse_rf1086_year_source(fixture['storage_text'])
    basis = manifest_basis(source)
    if annual:
        proof = rf.build_rf1086_annual_readiness(source, basis.preview,
            replace(inputs_for(source), **(changes or {})))
        basis = replace(basis, annual_readiness=proof,
                        acknowledged_warning_codes=proof.required_warning_codes)
    return basis


@pytest.mark.parametrize('fixture', GOLDENS, ids=lambda row: row['kind'])
@pytest.mark.parametrize('annual', [False, True])
@pytest.mark.parametrize('raw', [False, True], ids=['canonical-preview-only', 'captured-payload'])
def test_released_v1_v2_approval_composition_is_identical_for_every_old_source(fixture, annual, raw):
    basis = legacy(fixture, annual=annual)
    fresh = rf.build_rf1086_source_approval_manifest(basis)
    kwargs = commitment(basis.preview, raw)
    historical = retained.build_manifest(basis, **kwargs)
    assert historical == fresh
    assert rf.serialize_rf1086_source_approval_manifest(historical) == rf.serialize_rf1086_source_approval_manifest(fresh)
    retained.assert_matches(fresh, basis, **kwargs)
    if annual:
        parsed = readiness.parse_annual_binding(fresh.manifest['annualReadiness'],
            basis.source, basis.preview, **kwargs)
        assert parsed == basis.annual_readiness
        assert readiness.annual_binding(parsed, basis.source, basis.preview, **kwargs) == fresh.manifest['annualReadiness']


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('amendments', [0, 1, 2])
@pytest.mark.parametrize('raw', [False, True])
def test_v3_retains_full_original_and_amended_source_identity(kind, amendments, raw):
    basis = basis_v3(kind, amendments=amendments)
    fresh = rf.build_rf1086_source_approval_manifest_v3(basis)
    kwargs = commitment(basis.preview, raw)
    assert retained.build_manifest(basis, **kwargs) == fresh
    retained.assert_matches(fresh, basis, **kwargs)
    proof = readiness.parse_annual_binding(fresh.manifest['annualReadiness'],
        basis.source, basis.preview, **kwargs)
    assert proof == basis.annual_readiness
    assert proof.source.evidence.freshness == basis.source.freshness


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('changes', [
    {'period_lock_ids': ()},
    {'documents': (rf.Rf1086AnnualDocumentStatus(uid(9011), 'RF-1086', 'missing_accepted_warning'),)},
    {'period_lock_ids': (), 'documents': (rf.Rf1086AnnualDocumentStatus(uid(9011), 'RF-1086', 'missing_accepted'),)},
])
def test_retained_annual_reassesses_required_and_accepted_warnings_separately(version, changes):
    basis = legacy(GOLDENS[0], annual=True, changes=changes) if version == 1 else basis_v3(annual_changes=changes)
    fresh = (rf.build_rf1086_source_approval_manifest(basis) if version == 1
             else rf.build_rf1086_source_approval_manifest_v3(basis))
    actual = retained.build_manifest(basis, **commitment(basis.preview))
    assert actual == fresh
    assert actual.manifest['review']['acknowledgedWarningCodes'] == basis.annual_readiness.required_warning_codes
    proof = readiness.parse_annual_binding(actual.manifest['annualReadiness'], basis.source,
        basis.preview, **commitment(basis.preview))
    assert proof.accepted_warning_codes == basis.annual_readiness.accepted_warning_codes
    assert proof.required_warning_codes == basis.annual_readiness.required_warning_codes


@pytest.mark.parametrize('version', [1, 2, 3])
def test_exact_submission_predecessor_identity_and_reason_are_preserved(version):
    basis = basis_v3() if version == 3 else legacy(GOLDENS[0], annual=version == 2)
    prior = rf.Rf1086SourceCorrectionPredecessor(rf.SubmissionId(uid(9041)), 'd' * 64,
        '  Approved correction — årsak\n  ')
    basis = replace(basis, predecessor=prior)
    expected = (rf.build_rf1086_source_approval_manifest_v3(basis) if version == 3
                else rf.build_rf1086_source_approval_manifest(basis))
    actual = retained.build_manifest(basis, **commitment(basis.preview))
    assert actual == expected
    assert actual.manifest['predecessor']['reason'] == prior.reason


@pytest.mark.parametrize('version', [1, 2])
def test_blocked_annual_proof_is_historical_evidence_but_cannot_back_an_approved_manifest(version):
    basis = (legacy(GOLDENS[0], annual=True, changes={'has_unpaid_items': True}) if version == 1
             else basis_v3(annual_changes={'has_unpaid_items': True}))
    assert basis.annual_readiness.readiness_status == 'blocked'
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        retained.build_manifest(basis, **commitment(basis.preview))


def test_retained_manifest_comparison_does_not_accept_a_different_self_consistent_approval():
    basis = basis_v3()
    approved = retained.build_manifest(basis, **commitment(basis.preview))
    other = replace(basis, entitlement_id=uid(9051))
    assert retained.build_manifest(other, **commitment(other.preview)).manifest_sha256 != approved.manifest_sha256
    with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'):
        retained.assert_matches(approved, other, **commitment(other.preview))


def test_old_source_economic_representations_are_not_reinterpreted_by_retained_validation():
    # The public source codec can preserve a different display representation
    # from the original typed command. Use the actual command/preview objects.
    from test_rf1086_year_source import basis, prepare
    command, context = basis()
    for amount in (30000, 30000.0):
        paid_in = replace(command.paid_in, opening_capital=amount, closing_capital=amount)
        source = prepare(replace(command, paid_in=paid_in), context)
        value = manifest_basis(source)
        expected = rf.build_rf1086_source_approval_manifest(value)
        assert retained.build_manifest(value, **commitment(value.preview)) == expected
        assert value.preview == preview_source(source)[0]
