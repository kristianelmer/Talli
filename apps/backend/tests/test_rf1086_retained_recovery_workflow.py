"""Retained v3 recovery through the application; synthetic sessions, no live I/O."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from talli_backend.application import shareholder_register_filing_workflow as workflow
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_archive_storage_v6 import forbid_fresh
from test_rf1086_retained_recovery_correction_adversarial import corrected
from test_rf1086_retained_source_dispatch import retained_submission
from test_rf1086_source_recovery import RecoverySession, recover, submission_for
from test_shareholder_register_filing_production import (
    BillingPilotCaseProfile, DOCUMENT, NOW, ProductionPilotEntitlementId,
    ReadOnlyArchive, feedback, page,
)


def nonterminal_archive(kind='cash_issue', amendments=2, *, correction=True):
    archive = retained_submission(kind, amendments, 'accepted', correction=correction)
    row = replace(archive.production_submissions[0], status='processing',
        feedback_state='processing', feedback_artifact_count=0)
    return replace(archive, production_submissions=(row,), feedback_artifacts=(),
        production_events=tuple(event for event in archive.production_events
            if not event.operation_name.startswith('reconciliation:')))


class RetainedRecoverySession(RecoverySession):
    """Only override fixture identity and references; retain the old read-only ports."""
    def __init__(self, archive=None):
        super().__init__()
        self.archive = archive if archive is not None else nonterminal_archive()
        self.submission = submission_for(self.archive)
        saved = next(item for item in self.archive.approvals if item.id == self.submission.approval_id)
        self.approval = rf.Rf1086Approval(saved.id, saved.entitlement_id, saved.preview_id,
            saved.company_id, saved.user_id, saved.income_year, saved.obligation,
            saved.case_profile, True, saved.manifest_hash, saved.manifest)
        self.company = SimpleNamespace(id=saved.company_id, role='owner',
            org_number=saved.manifest['organizationNumber'])
        self.pilot = replace(self.pilot, entitlement_id=ProductionPilotEntitlementId(saved.entitlement_id),
            company_id=self.archive.company_id, user_id=self.actor_id.subject,
            income_year=self.archive.income_year, case_profile=BillingPilotCaseProfile.RF1086_FULL_YEAR_V1)
        self.connection = rf.Rf1086Connection(str(self.pilot.system_user_request_id),
            saved.company_id, saved.user_id, saved.obligation,
            self.pilot.system_user_external_reference, 'accepted', True)
        refs = json.loads(self.archive.production_submissions[0].authority_references['confirm'])
        self.dialog_id, self.reference = refs['dialogId'], refs['forsendelseId']
        self.authority = ReadOnlyArchive([page([rf.Rf1086DocumentReference(DOCUMENT)])],
            {DOCUMENT: rf.Rf1086AuthorityDocument(DOCUMENT, 'application/xml',
                feedback(reference=self.reference, year=self.submission.income_year).encode())})
        self.read_references = []
        self.discoveries = []

    async def read_claimed_reference(self, submission, lease):
        assert (submission, lease) == (self.submission.id, self.lease)
        self.read_references.append(('transmission', self.reference))
        return self.reference

    async def read_claimed_dialog_id(self, submission, lease):
        assert (submission, lease) == (self.submission.id, self.lease)
        self.read_references.append(('dialog', self.dialog_id))
        return self.dialog_id

    def feedback_journal(self, **args):
        assert args == dict(submission_id=self.submission.id, company_id=self.submission.company_id,
            income_year=self.submission.income_year, forsendelse_id=self.reference, lease_id=self.lease)
        return self.journal

    async def discover(self, *, organization_number, dialog_id, forsendelse_id):
        assert (organization_number, dialog_id, forsendelse_id) == (
            self.company.org_number, self.dialog_id, self.reference)
        self.discoveries.append((organization_number, dialog_id, forsendelse_id))
        return (rf.Rf1086FeedbackTransmission(self.dialog_id, DOCUMENT, self.reference,
            NOW.isoformat(), (DOCUMENT,), 'Acceptance'),)


@pytest.mark.parametrize('kind', ['cash_issue', 'loss_covering_reduction'])
@pytest.mark.parametrize('amendments', [0, 1, 2])
def test_retained_capital_recovery_reaches_read_only_feedback(kind, amendments, monkeypatch):
    archive = nonterminal_archive(kind, amendments)
    source = archive.source_history.year_sources[-1]
    assert source.governance_projection.chain_count == 1
    assert source.governance_projection.chains[0].amendment_count == amendments
    assert len(archive.source_history.register_observations) == amendments + 1
    assert len(archive.withdrawal_capture_records) == amendments
    assert len(archive.source_history.year_sources) == 2  # Genuine v1 -> v2 source history.
    session = RetainedRecoverySession(archive)
    seen = []
    original = workflow.reconcile_journaled_rf1086_production

    async def observe(journal, authority, recovery, **kwargs):
        seen.append(recovery)
        assert recovery.hovedskjema_xml == archive.previews[0].hovedskjema_xml
        assert dict(recovery.underskjema_xml) == dict(archive.previews[0].underskjema_xml)
        return await original(journal, authority, recovery, **kwargs)

    monkeypatch.setattr(workflow, 'reconcile_journaled_rf1086_production', observe)
    forbid_fresh(monkeypatch)  # All fixture construction precedes these sentinels.
    result = recover(session)
    assert (result.state, result.error_code, result.requires_manual_retry) == ('accepted', None, False)
    assert session.events == ['billing', 'configuration', 'claim', 'archive', 'read_token', 'discard', 'release']
    assert session.read_references == [('transmission', session.reference), ('dialog', session.dialog_id)]
    assert session.discoveries == [(session.company.org_number, session.dialog_id, session.reference)]
    assert set(name for name, _ in session.authority.calls) == {'get'}
    assert len(seen) == 1
    assert len(session.journal.artifacts) == 2


@pytest.mark.parametrize('kind', ['no_activity', 'formation', 'dividend', 'mixed'])
@pytest.mark.parametrize('state', ['sent', 'unknown', 'action_required'])
def test_reconciler_receives_exact_saved_xml_and_source_keys(kind, state, monkeypatch):
    session = RetainedRecoverySession(nonterminal_archive(kind, 0, correction=False))
    session.submission = replace(session.submission, feedback_state=state)
    saved = next(preview for preview in session.archive.previews if preview.id == session.approval.preview_id)
    seen = []
    original = workflow.reconcile_journaled_rf1086_production

    async def observe(journal, authority, recovery, **kwargs):
        seen.append(recovery)
        assert recovery.submission_id == session.submission.id
        assert recovery.hovedskjema_xml == saved.hovedskjema_xml
        assert dict(recovery.underskjema_xml) == dict(saved.underskjema_xml)
        assert all(name.startswith('source_') for name in recovery.underskjema_xml)
        assert recovery.forsendelse_id == session.reference
        assert recovery.dialog_id == session.dialog_id
        assert kwargs == dict(discovery=session.discovery, initial_poll=False)
        return await original(journal, authority, recovery, **kwargs)

    monkeypatch.setattr(workflow, 'reconcile_journaled_rf1086_production', observe)
    forbid_fresh(monkeypatch)
    assert recover(session).state == 'accepted'
    assert len(seen) == 1
    assert session.events[-2:] == ['discard', 'release']


@pytest.mark.parametrize('terminal_child', [False, True])
def test_earlier_nonterminal_view_recovers_confirmed_ancestor_original(terminal_child, monkeypatch):
    # Synthetic read ordering only: actual SQL will not grant a new lease to a
    # submission already terminal when read_submission observes it.
    archive = corrected(terminal_child)
    session = RetainedRecoverySession(archive)
    session.submission = replace(session.submission, feedback_state='processing')
    assert archive.production_submissions[0].feedback_state == 'accepted'
    assert str(archive.submission_head.submission_id) != session.submission.id
    seen = []
    original = workflow.reconcile_journaled_rf1086_production

    async def observe(journal, authority, recovery, **kwargs):
        seen.append(recovery)
        return await original(journal, authority, recovery, **kwargs)

    monkeypatch.setattr(workflow, 'reconcile_journaled_rf1086_production', observe)
    forbid_fresh(monkeypatch)
    assert recover(session).state == 'accepted'
    assert len(seen) == 1 and seen[0].submission_id == archive.production_submissions[0].id
    assert seen[0].hovedskjema_xml == archive.previews[0].hovedskjema_xml
    assert (seen[0].dialog_id, seen[0].forsendelse_id) == (session.dialog_id, session.reference)


@pytest.mark.parametrize('state', ['accepted', 'rejected'])
def test_terminal_retained_submission_does_not_acquire_lease_or_archive(state, monkeypatch):
    session = RetainedRecoverySession(retained_submission(status=state))
    forbid_fresh(monkeypatch)
    result = recover(session)
    assert (result.state, result.error_code, result.requires_manual_retry) == (state, None, False)
    assert session.events == session.read_references == session.authority.calls == []


@pytest.mark.parametrize('corrupt', [False, True])
def test_existing_http_recovery_retains_success_and_proof_denial_wire(corrupt, monkeypatch):
    from fastapi.testclient import TestClient
    from talli_backend.main import create_app
    session = RetainedRecoverySession()
    if corrupt:
        session.archive = replace(session.archive, source_submission_claims=())

    class Factory:
        async def session(self, token):
            assert token == 'synthetic-owner'
            return session

    client = TestClient(create_app(shareholder_register_filing_session_factory=Factory()))
    forbid_fresh(monkeypatch)
    response = client.post('/api/v1/legacy-rf1086/feedback-reconciliations',
        headers={'Authorization': 'Bearer synthetic-owner'}, json={'submissionId': session.submission.id})
    assert response.status_code == 200, response.text
    assert response.json() == (dict(state='processing', errorCode='basis_unavailable', requiresManualRetry=True)
        if corrupt else dict(state='accepted', errorCode=None, requiresManualRetry=False))
    assert session.events[-1] == 'release'
    assert ('read_token' in session.events) is not corrupt
