"""Full-year manifests bind evidence and feed the existing submit-once journal."""
import asyncio
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from uuid import UUID

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_year_source import basis, prepare, ACTOR, NOW, DOCUMENT, REGISTER
from test_rf1086_source_preview import preview_source
from test_rf1086_capital_events import capital_case, ROOT
from test_rf1086_register_projection import formation_transfer_issue_case
from test_shareholder_register_filing_production import Authority, OperationJournal


def source_for(case):
    command, context = basis()
    shares = case.share_snapshot
    paid_in = rf.Rf1086PaidInSourceFacts(shares.previous_paid_in_share_capital,
        shares.current_paid_in_share_capital, shares.previous_paid_in_premium, shares.current_paid_in_premium)
    evidence, receipts = [], []
    for index, event in enumerate(case.events):
        governed = event.type in {'dividend', 'cash_issue', 'cash_nominal_increase', 'loss_covering_reduction'}
        receipt_id = str(UUID(int=100 + index)) if governed else None
        evidence.append(rf.Rf1086YearEventEvidence(index, rf.rf1086_year_source_digest(event), (DOCUMENT,), receipt_id))
        if governed:
            receipts.append(rf.Rf1086YearGovernanceReceipt(receipt_id, command.company_id, command.income_year,
                event.type, rf.rf1086_year_source_digest(rf.rf1086_governance_economic_facts(event)),
                'b' * 64, (context.documents[0].content_sha256,), True,
                REGISTER if event.type != 'dividend' else None, 'c' * 64 if event.type != 'dividend' else None))
    return prepare(replace(command, case=case, paid_in=paid_in, event_evidence=tuple(evidence),
        no_activity_confirmed=not case.events), replace(context, company=case.company,
        governance_receipts=tuple(receipts), governance_enumeration_sha256=rf.rf1086_year_source_digest(receipts)))


def manifest_basis(source=None):
    source = source or prepare(*basis())
    preview, _ = preview_source(source)
    return rf.Rf1086SourceApprovalManifestBasis(source, preview, ACTOR, str(UUID(int=70)), 'f' * 64, ())


def source_case(kind):
    if kind in {'no_activity', 'dividend', 'cash_issue'}:
        return basis(kind)[0].case
    if kind == 'mixed':
        return formation_transfer_issue_case()
    if kind in {'cash_nominal_increase', 'loss_covering_reduction'}:
        raw = capital_case(kind)
    else:
        raw = json.loads((ROOT / 'tests/fixtures/rf1086/stiftelse.json').read_text())
    raw['share_snapshot'].setdefault('previous_paid_in_premium', 0)
    raw['share_snapshot'].setdefault('current_paid_in_premium', 0)
    return rf.parse_rf1086_case(raw)


@pytest.mark.parametrize('kind', ['no_activity', 'formation', 'dividend', 'cash_issue',
    'cash_nominal_increase', 'loss_covering_reduction', 'mixed'])
def test_supported_event_cases_bind_complete_source_and_use_existing_journal(kind):
    case = source_case(kind)
    if kind == 'mixed':
        case = replace(case, share_snapshot=replace(case.share_snapshot, previous_paid_in_premium=0))
    value = manifest_basis(source_for(case))
    approved = rf.build_rf1086_source_approval_manifest(value)
    manifest = approved.manifest
    assert manifest['schemaVersion'] == 'production-source-approval-v1'
    assert manifest['caseProfile'] == 'rf1086_full_year_v1'
    assert manifest['source']['sha256'] == value.source.source_sha256
    assert manifest['source']['caseSha256'] == value.source.case_sha256
    assert manifest['freshness']['documentsSha256'] == value.source.freshness.documents_sha256
    assert manifest['review']['sha256'] == value.review_sha256
    assert manifest['predecessor'] is None
    rf.assert_rf1086_source_approval_manifest_matches(approved, value)
    journal, authority = OperationJournal(), Authority()
    command = rf.JournaledRf1086ProductionInput('synthetic-source', 2025,
        value.preview.hovedskjema_xml, approved.underskjema_xml, approved.document_order)
    asyncio.run(rf.execute_journaled_rf1086_production(command, journal=journal, authority_client=authority))
    posted = [args['xml'] for name, args in authority.calls if name == 'sub']
    assert posted == [value.preview.underskjema_xml[row['shareholderId']] for row in manifest['documentHashes'][1:]]
    assert all(len(name) <= 120 for name in journal.operations)
    count = len(authority.calls)
    asyncio.run(rf.execute_journaled_rf1086_production(command, journal=journal, authority_client=authority))
    assert len(authority.calls) == count


@pytest.mark.parametrize('identity', ['owner', 'é', 'e\u0301', '😀', '10', ' A ', 'aksjonær' * 100])
def test_stable_non_uuid_shareholder_ids_fit_the_existing_journal(identity):
    case = basis()[0].case
    case = replace(case, shareholders=(replace(case.shareholders[0], id=identity),),
        shareholder_snapshots=(replace(case.shareholder_snapshots[0], shareholder_id=identity),))
    value = manifest_basis(source_for(case))
    result = rf.build_rf1086_source_approval_manifest(value)
    row = result.manifest['documentHashes'][1]
    assert row['shareholderId'] == identity
    key = 'source_' + hashlib.sha256(('rf1086-source-shareholder-v1:' + identity).encode()).hexdigest()
    assert result.document_order == (key,)
    assert result.underskjema_xml[key] == value.preview.underskjema_xml[identity]
    assert len('post_underskjema:' + key) <= 120


@pytest.mark.parametrize('field,new', [('actor_id', rf.ActorId(ACTOR.kind, str(UUID(int=81)))),
    ('entitlement_id', str(UUID(int=82))), ('review_sha256', 'a' * 64)])
def test_authorization_identity_or_review_change_invalidates_the_manifest(field, new):
    value = manifest_basis()
    approved = rf.build_rf1086_source_approval_manifest(value)
    with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'):
        rf.assert_rf1086_source_approval_manifest_matches(approved, replace(value, **{field: new}))


def test_identical_xml_after_source_correction_requires_a_new_approval_identity():
    command, context = basis()
    source = prepare(command, context)
    corrected = prepare(replace(command, supersedes_source_id=source.source_id,
        supersedes_source_sha256=source.source_sha256, correction_reason='Source evidence corrected'), context,
        previous=source, source_id=rf.Rf1086YearSourceId(str(UUID(int=90))), confirmed_at=NOW + timedelta(days=1))
    before, after = manifest_basis(source), manifest_basis(corrected)
    assert before.preview.hovedskjema_xml == after.preview.hovedskjema_xml
    approved = rf.build_rf1086_source_approval_manifest(before)
    assert approved.manifest_sha256 != rf.build_rf1086_source_approval_manifest(after).manifest_sha256
    with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'):
        rf.assert_rf1086_source_approval_manifest_matches(approved, after)


def test_correction_predecessor_and_exact_reason_are_bound_independently_of_source_correction():
    value = manifest_basis()
    prior = rf.Rf1086SourceCorrectionPredecessor(rf.SubmissionId(str(UUID(int=60))), 'c' * 64, 'Owner reviewed correction')
    value = replace(value, predecessor=prior)
    approved = rf.build_rf1086_source_approval_manifest(value)
    assert approved.manifest['predecessor']['reason'] == prior.reason
    for changed in (None, replace(prior, reason='Another reason'), replace(prior, manifest_sha256='d' * 64),
                    replace(prior, submission_id=rf.SubmissionId(str(UUID(int=61))))):
        with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'):
            rf.assert_rf1086_source_approval_manifest_matches(approved, replace(value, predecessor=changed))


@pytest.mark.parametrize('change', ['unknown_version', 'extra_key', 'missing_key', 'xml', 'order', 'digest', 'bool_year'])
def test_manifest_verification_rejects_partial_or_altered_approvals(change):
    value = manifest_basis(); approved = rf.build_rf1086_source_approval_manifest(value)
    manifest = dict(approved.manifest)
    if change == 'unknown_version': manifest['schemaVersion'] = 'production-approval-v1'
    if change == 'extra_key': manifest['trusted'] = True
    if change == 'missing_key': del manifest['freshness']
    if change == 'bool_year': manifest['incomeYear'] = True
    changes = {'manifest': manifest}
    if change == 'xml': changes['underskjema_xml'] = {approved.document_order[0]: '<changed/>'}
    if change == 'order': changes['document_order'] = ()
    if change == 'digest': changes['manifest_sha256'] = '0' * 64
    with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'):
        rf.assert_rf1086_source_approval_manifest_matches(replace(approved, **changes), value)


@pytest.mark.parametrize('change', ['source', 'preview', 'review', 'entitlement', 'warning', 'duplicate_warning', 'reason'])
def test_invalid_source_or_unreviewed_basis_never_builds_an_approval(change):
    value = manifest_basis()
    if change == 'source': value = replace(value, source=replace(value.source, source_sha256='0' * 64))
    if change == 'preview': value = replace(value, preview=replace(value.preview, hovedskjema_xml='<changed/>'))
    if change == 'review': value = replace(value, review_sha256='invalid')
    if change == 'entitlement': value = replace(value, entitlement_id='not-uuid')
    if change == 'warning': value = replace(value, acknowledged_warning_codes=('not-reviewed',))
    if change == 'duplicate_warning': value = replace(value, acknowledged_warning_codes=('not-reviewed', 'not-reviewed'))
    if change == 'reason': value = replace(value, predecessor=rf.Rf1086SourceCorrectionPredecessor(
        rf.SubmissionId(str(UUID(int=60))), 'c' * 64, '   '))
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        rf.build_rf1086_source_approval_manifest(value)


def test_manifest_and_journal_documents_are_immutable():
    approved = rf.build_rf1086_source_approval_manifest(manifest_basis())
    with pytest.raises(TypeError): approved.manifest['source']['sha256'] = 'a' * 64
    with pytest.raises(TypeError): approved.underskjema_xml[approved.document_order[0]] = '<changed/>'


def test_document_order_is_independent_of_preview_mapping_insertion_order():
    case = formation_transfer_issue_case()
    case = replace(case, share_snapshot=replace(case.share_snapshot, previous_paid_in_premium=0))
    value = manifest_basis(source_for(case))
    approved = rf.build_rf1086_source_approval_manifest(value)
    alternate = replace(value, preview=replace(value.preview,
        underskjema_xml=dict(reversed(tuple(value.preview.underskjema_xml.items())))))
    assert rf.build_rf1086_source_approval_manifest(alternate) == approved
    assert [row['shareholderId'] for row in approved.manifest['documentHashes'][1:]] == ['buyer', 'founder']


def test_preview_identity_must_be_an_operational_uuid():
    value = manifest_basis()
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        rf.build_rf1086_source_approval_manifest(replace(value,
            preview=replace(value.preview, preview_id='not-an-id')))
