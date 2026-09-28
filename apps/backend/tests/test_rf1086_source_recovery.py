"""Full-year recovery uses claimed original bytes and never acquires a POST port."""
import asyncio
from dataclasses import fields, replace
import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from talli_backend.application.shareholder_register_filing_workflow import reconcile_rf1086_production, send_approved_rf1086_production_filing
from talli_backend.application.shareholder_register_filing_session import Rf1086ReadOnlyBinding
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_source_submission_archive import source_submission_archive
from test_rf1086_year_source import ACTOR
from test_shareholder_register_filing_production import (
    BillingQueries, FeedbackJournal, ReadOnlyArchive, page, feedback, DIALOG, TRANSMISSION, DOCUMENT,
    BillingSnapshot, BillingPilotCaseProfile, ProductionPilotEntitlementId, ProductionPilotStatus,
    CoordinatorSession, Timestamp, NOW, timedelta,
)


def recovery_archive(kind='formation'):
    archive = source_submission_archive(kind)
    confirmation = json.dumps({'dialogId': DIALOG, 'forsendelseId': TRANSMISSION}, separators=(',', ':'))
    submission = replace(archive.production_submissions[0], status='processing', feedback_state='processing',
        feedback_artifact_count=0, authority_references={**archive.production_submissions[0].authority_references, 'confirm': confirmation})
    events = tuple(replace(event, authority_reference=confirmation) if event.operation_name == 'confirm' else event
        for event in archive.production_events if not event.operation_name.startswith('reconciliation:'))
    return replace(archive, production_submissions=(submission,), production_events=events, feedback_artifacts=())


def submission_for(archive):
    row = archive.production_submissions[0]
    return rf.Rf1086Submission(**{field.name: getattr(row, field.name) for field in fields(rf.Rf1086Submission)})


def prepare(archive, **kwargs):
    args = dict(query=rf.Rf1086ArchiveQuery(archive.company_id, archive.income_year, ACTOR),
        submission=submission_for(archive), forsendelse_id=TRANSMISSION, dialog_id=DIALOG)
    return rf.prepare_rf1086_source_reconciliation(archive, **(args | kwargs))


@pytest.mark.parametrize('kind', ['no_activity', 'formation', 'dividend', 'cash_issue', 'loss_covering_reduction'])
def test_retained_claim_payload_recovers_exact_source_keys_and_bytes(kind):
    archive = recovery_archive(kind)
    payload = prepare(archive)
    assert payload.hovedskjema_xml == archive.previews[0].hovedskjema_xml
    assert payload.underskjema_xml == archive.previews[0].underskjema_xml
    assert all(key.startswith('source_') for key in payload.underskjema_xml)
    assert payload.organization_number == archive.approvals[0].manifest['organizationNumber']
    with pytest.raises(TypeError): payload.underskjema_xml['extra'] = 'altered'


@pytest.mark.parametrize('change', ['claim', 'head', 'source', 'preview', 'post', 'confirmation', 'actor', 'profile', 'year'])
def test_missing_or_changed_original_submission_evidence_cannot_drive_a_read(change):
    archive = recovery_archive()
    args = {}
    if change == 'claim': archive = replace(archive, source_submission_claims=())
    if change == 'head': archive = replace(archive, submission_head=None)
    if change == 'source': archive = replace(archive, source_approval_lineage=())
    if change == 'preview': archive = replace(archive, previews=(replace(archive.previews[0], hovedskjema_xml='<changed/>'),))
    if change == 'post': archive = replace(archive, production_events=archive.production_events[1:])
    if change == 'confirmation': args['forsendelse_id'] = DOCUMENT
    if change == 'actor': args['query'] = rf.Rf1086ArchiveQuery(archive.company_id, archive.income_year, replace(ACTOR, subject=type(ACTOR.subject)(DOCUMENT)))
    if change == 'profile': args['submission'] = replace(submission_for(archive), case_profile='rf1086_no_activity_v1')
    if change == 'year': args['submission'] = replace(submission_for(archive), income_year=2024)
    with pytest.raises(rf.Rf1086ProductionError): prepare(archive, **args)


class RecoverySession:
    def __init__(self, kind='formation'):
        self.archive = recovery_archive(kind)
        self.submission = submission_for(self.archive)
        a = self.archive.approvals[0]
        self.approval = rf.Rf1086Approval(a.id, a.entitlement_id, a.preview_id, a.company_id, a.user_id,
            a.income_year, a.obligation, a.case_profile, True, a.manifest_hash, a.manifest)
        self.actor_id = ACTOR
        self.events = []
        self.company = SimpleNamespace(id=a.company_id, role='owner', org_number=a.manifest['organizationNumber'])
        self.pilot = replace(BillingQueries([]).pilot, entitlement_id=ProductionPilotEntitlementId(a.entitlement_id),
            company_id=self.archive.company_id, user_id=ACTOR.subject, income_year=self.archive.income_year,
            case_profile=BillingPilotCaseProfile.RF1086_FULL_YEAR_V1, status=ProductionPilotStatus.REVOKED,
            expires_at=Timestamp(NOW-timedelta(days=1)))
        self.billing = SimpleNamespace(snapshot=self.billing_snapshot)
        self.connection = rf.Rf1086Connection(str(self.pilot.system_user_request_id), a.company_id, a.user_id,
            a.obligation, self.pilot.system_user_external_reference, 'accepted', True)
        self.journal = FeedbackJournal('processing')
        self.authority = ReadOnlyArchive([page([rf.Rf1086DocumentReference(DOCUMENT)])],
            {DOCUMENT: rf.Rf1086AuthorityDocument(DOCUMENT, 'application/xml', feedback().encode())})
        self.discovery = SimpleNamespace(read_feedback_transmissions=self.discover)
        self.busy = False
        self.fail_archive = False
    async def billing_snapshot(self, query):
        self.events.append('billing')
        assert query.company_ids == (self.archive.company_id,) and query.actor_id == ACTOR
        return BillingSnapshot((), (), (self.pilot,))
    async def read_submission(self, identifier):
        assert identifier == self.submission.id
        return self.submission
    async def read_approval(self, identifier):
        assert identifier == self.approval.id
        return self.approval
    async def company_record(self, identifier): return self.company
    async def read_connection(self, request, company): return self.connection
    def require_configuration(self): self.events.append('configuration')
    async def claim_feedback_lease(self, submission, lease):
        self.events.append('claim'); self.lease = lease
        return not self.busy
    async def read_claimed_reference(self, submission, lease): return TRANSMISSION
    async def read_claimed_dialog_id(self, submission, lease): return DIALOG
    async def archive_source(self, query):
        self.events.append('archive')
        assert query.actor_id == ACTOR and query.company_id == self.archive.company_id
        if self.fail_archive: raise rf.ShareholderRegisterFilingError.unavailable()
        return self.archive
    async def bind_read_only_authority(self, company, connection):
        self.events.append('read_token')
        return Rf1086ReadOnlyBinding(self.authority, lambda: self.events.append('discard'), self.discovery)
    def feedback_journal(self, **args):
        assert args == dict(submission_id=self.submission.id, company_id=self.submission.company_id,
            income_year=self.submission.income_year, forsendelse_id=TRANSMISSION, lease_id=self.lease)
        return self.journal
    async def release_feedback_lease(self, submission, lease):
        assert lease == self.lease
        self.events.append('release')
    async def discover(self, *, organization_number, dialog_id, forsendelse_id):
        assert (organization_number, dialog_id, forsendelse_id) == (self.company.org_number, DIALOG, TRANSMISSION)
        return (rf.Rf1086FeedbackTransmission(DIALOG, DOCUMENT, TRANSMISSION, NOW.isoformat(), (DOCUMENT,), 'Acceptance'),)
    # Deliberately no read_preview, mutation/token, current source, MFA or send API.


def recover(session):
    return asyncio.run(reconcile_rf1086_production(session, session.submission.id))


@pytest.mark.parametrize('kind', ['no_activity', 'formation', 'dividend', 'cash_issue', 'loss_covering_reduction'])
@pytest.mark.parametrize('state', ['processing', 'unknown', 'action_required'])
def test_full_year_recovery_uses_only_read_ports_after_expired_pilot_and_invalidated_approval(kind, state):
    session = RecoverySession(kind)
    session.submission = replace(session.submission, feedback_state=state)
    result = recover(session)
    assert (result.state, result.error_code, result.requires_manual_retry) == ('accepted', None, False)
    assert session.events == ['billing', 'configuration', 'claim', 'archive', 'read_token', 'discard', 'release']
    assert set(name for name, _ in session.authority.calls) <= {'list', 'get'}
    assert len(session.journal.artifacts) == 2
    artifact = next(iter(session.journal.artifacts.values()))
    assert artifact.submission_id == session.submission.id and artifact.company_id == session.submission.company_id


@pytest.mark.parametrize('failure', ['archive', 'claim', 'foreign-company', 'missing-confirmation'])
def test_unproven_source_recovery_releases_lease_before_acquiring_provider_token(failure):
    session = RecoverySession()
    if failure == 'archive': session.fail_archive = True
    if failure == 'claim': session.archive = replace(session.archive, source_submission_claims=())
    if failure == 'foreign-company': session.company.org_number = '999999999'
    if failure == 'missing-confirmation': session.archive = replace(session.archive,
        production_events=tuple(e for e in session.archive.production_events if e.operation_name != 'confirm'))
    result = recover(session)
    assert result.requires_manual_retry and result.error_code
    assert session.events[-1] == 'release' and 'read_token' not in session.events
    assert not session.authority.calls


def test_busy_full_year_recovery_does_not_read_archive_or_release_another_lease():
    session = RecoverySession(); session.busy = True
    result = recover(session)
    assert result.error_code == 'status_busy'
    assert session.events == ['billing', 'configuration', 'claim']


def test_legacy_send_cannot_dispatch_full_year_approval():
    session = CoordinatorSession()
    session.approval = replace(session.approval, case_profile='rf1086_full_year_v1')
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        asyncio.run(send_approved_rf1086_production_filing(session, session.approval.id))
    assert session.events == ['configuration', 'approval']
    assert not session.mutation_authority.calls


def test_authenticated_http_recovery_reaches_full_year_read_only_workflow():
    from fastapi.testclient import TestClient
    from talli_backend.main import create_app
    session = RecoverySession()
    class Factory:
        async def session(self, token):
            assert token == 'synthetic-owner'
            return session
    client = TestClient(create_app(shareholder_register_filing_session_factory=Factory()))
    response = client.post('/api/v1/legacy-rf1086/feedback-reconciliations',
        headers={'Authorization': 'Bearer synthetic-owner'}, json={'submissionId': session.submission.id})
    assert response.status_code == 200, response.text
    assert response.json() == {'state': 'accepted', 'errorCode': None, 'requiresManualRetry': False}
    assert session.events.index('archive') < session.events.index('read_token')
    assert session.events[-2:] == ['discard', 'release']


def test_unknown_submission_without_successful_confirmation_does_not_invent_a_read_reference():
    archive = source_submission_archive(status='approved')
    archive = replace(archive, production_submissions=(replace(archive.production_submissions[0], status='unknown', feedback_state='unknown'),))
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        prepare(archive)


def test_duplicate_confirmation_keys_cannot_select_a_recovery_target():
    archive = recovery_archive()
    reference = '{"dialogId":"wrong","dialogId":"' + DIALOG + '","forsendelseId":"' + TRANSMISSION + '"}'
    submission = replace(archive.production_submissions[0], authority_references={**archive.production_submissions[0].authority_references, 'confirm': reference})
    archive = replace(archive, production_submissions=(submission,), production_events=tuple(
        replace(event, authority_reference=reference) if event.operation_name == 'confirm' else event for event in archive.production_events))
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        prepare(archive)
