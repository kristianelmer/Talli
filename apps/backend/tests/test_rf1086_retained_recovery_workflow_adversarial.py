"""Independent retained recovery ordering; synthetic ports establish no SQL authority."""
import asyncio
from dataclasses import fields, replace
import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from talli_backend.application import shareholder_register_filing_workflow as workflow
from talli_backend.application.shareholder_register_filing_session import Rf1086ReadOnlyBinding
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_source_recovery import RecoverySession
from test_rf1086_retained_source_dispatch import retained_submission
from test_rf1086_retained_recovery_correction_adversarial import corrected
from test_rf1086_archive_storage_v6 import forbid_fresh
from test_rf1086_year_source import ACTOR
from test_shareholder_register_filing_production import (
    FeedbackJournal, ReadOnlyArchive, page, feedback, DOCUMENT, NOW,
    ProductionPilotEntitlementId, BillingPilotCaseProfile,
)

DIALOG = 'abcdef01-2345-6789-abcd-ef0123456789'
TRANSMISSION = 'fedcba98-7654-3210-fedc-ba9876543210'


def replace_confirmation(archive, text):
    selected = archive.production_submissions[0]
    return replace(archive, production_submissions=tuple(
        replace(row, authority_references={**row.authority_references, 'confirm': text})
        if row.id == selected.id else row for row in archive.production_submissions),
        production_events=tuple(replace(row, authority_reference=text)
            if row.submission_id == selected.id and row.operation_name == 'confirm' else row
            for row in archive.production_events))


def processing_archive():
    archive = retained_submission('loss_covering_reduction', 2, 'accepted')
    source = archive.source_approval_lineage[0].source
    assert len(source.governance_projection.chains) == 1
    assert source.governance_projection.chains[0].amendment_count == 2
    assert len(archive.source_history.register_observations) == 3
    assert len(archive.withdrawal_capture_records) == 2
    archive = replace(archive, production_submissions=(replace(archive.production_submissions[0],
        status='processing', feedback_state='processing', feedback_artifact_count=0),),
        production_events=tuple(e for e in archive.production_events
            if not e.operation_name.startswith('reconciliation:')), feedback_artifacts=())
    return replace_confirmation(archive, json.dumps(
        {'forsendelseId': TRANSMISSION, 'dialogId': DIALOG}, indent=2))


class IndependentSession(RecoverySession):
    """Reuse frozen old ports, replacing every selected original reference coherently."""
    def __init__(self, archive=None):
        super().__init__()
        self.archive = processing_archive() if archive is None else archive
        row = self.archive.production_submissions[0]
        a = next(a for a in self.archive.approvals if a.id == row.approval_id)
        self.submission = rf.Rf1086Submission(**{f.name: getattr(row, f.name)
            for f in fields(rf.Rf1086Submission)})
        self.approval = rf.Rf1086Approval(a.id, a.entitlement_id, a.preview_id, a.company_id,
            a.user_id, a.income_year, a.obligation, a.case_profile, True, a.manifest_hash, a.manifest)
        self.company = SimpleNamespace(id=a.company_id, role='owner', org_number=a.manifest['organizationNumber'])
        self.pilot = replace(self.pilot, entitlement_id=ProductionPilotEntitlementId(a.entitlement_id),
            company_id=self.archive.company_id, user_id=ACTOR.subject, income_year=self.archive.income_year,
            case_profile=BillingPilotCaseProfile.RF1086_FULL_YEAR_V1)
        self.connection = rf.Rf1086Connection(str(self.pilot.system_user_request_id), a.company_id,
            a.user_id, a.obligation, self.pilot.system_user_external_reference, 'accepted', True)
        saved = json.loads(row.authority_references['confirm'])
        self.reference, self.dialog = saved['forsendelseId'], saved['dialogId']
        self.authority = ReadOnlyArchive([page([rf.Rf1086DocumentReference(DOCUMENT)])],
            {DOCUMENT: rf.Rf1086AuthorityDocument(DOCUMENT, 'application/xml',
                feedback(reference=self.reference, year=a.income_year).encode())})
        self.journal = FeedbackJournal('processing')
        self.discovery = SimpleNamespace(read_feedback_transmissions=self.discover)
        self.failure_at = None
        self.failure = RuntimeError('synthetic port failure')
        self.received = []

    def mark(self, name):
        self.events.append(name)
        if self.failure_at == name:
            raise self.failure

    async def read_submission(self, identifier):
        self.mark('submission')
        return await super().read_submission(identifier)

    async def company_record(self, identifier):
        self.mark('company')
        return self.company

    async def read_approval(self, identifier):
        self.mark('approval')
        return await super().read_approval(identifier)

    async def read_connection(self, request, company):
        self.mark('connection')
        return self.connection

    def require_configuration(self):
        self.mark('configuration')

    async def claim_feedback_lease(self, submission, lease):
        self.lease = lease
        self.mark('claim')
        return not self.busy

    async def read_claimed_reference(self, submission, lease):
        assert (submission, lease) == (self.submission.id, self.lease)
        self.mark('reference')
        return self.reference

    async def read_claimed_dialog_id(self, submission, lease):
        assert (submission, lease) == (self.submission.id, self.lease)
        self.mark('dialog')
        return self.dialog

    async def archive_source(self, query):
        self.mark('archive')
        assert query == rf.Rf1086ArchiveQuery(self.archive.company_id, self.archive.income_year, self.actor_id)
        return self.archive

    async def bind_read_only_authority(self, company, connection):
        self.mark('read_token')
        return Rf1086ReadOnlyBinding(self.authority, lambda: self.mark('discard'), self.discovery)

    def feedback_journal(self, **args):
        self.mark('journal')
        assert args == dict(submission_id=self.submission.id, company_id=self.submission.company_id,
            income_year=self.submission.income_year, forsendelse_id=self.reference, lease_id=self.lease)
        return self.journal

    async def release_feedback_lease(self, submission, lease):
        assert (submission, lease) == (self.submission.id, self.lease)
        self.mark('release')

    async def discover(self, *, organization_number, dialog_id, forsendelse_id):
        self.mark('discover')
        assert (organization_number, dialog_id, forsendelse_id) == (
            self.company.org_number, self.dialog, self.reference)
        return (rf.Rf1086FeedbackTransmission(self.dialog, DOCUMENT, self.reference,
            NOW.isoformat(), (DOCUMENT,), 'Acceptance'),)


def instrument(monkeypatch, session):
    prepare = workflow.prepare_rf1086_retained_source_reconciliation
    reconcile = workflow.reconcile_journaled_rf1086_production
    def actual_prepare(archive, **args):
        session.mark('validate')
        return prepare(archive, **args)
    async def actual_reconcile(journal, authority, payload, **kwargs):
        session.received.append((payload, kwargs['initial_poll']))
        return await reconcile(journal, authority, payload, **kwargs)
    monkeypatch.setattr(workflow, 'prepare_rf1086_retained_source_reconciliation', actual_prepare)
    monkeypatch.setattr(workflow, 'reconcile_journaled_rf1086_production', actual_reconcile)
    forbid_fresh(monkeypatch)


def run(session):
    return asyncio.run(workflow.reconcile_rf1086_production(session, session.submission.id))


def assert_no_effects(session):
    assert 'read_token' not in session.events and not session.authority.calls and not session.received


def test_real_retained_validation_passes_original_xml_and_pretty_confirmation(monkeypatch):
    session = IndependentSession()
    instrument(monkeypatch, session)
    result = run(session)
    assert (result.state, result.error_code, result.requires_manual_retry) == ('accepted', None, False)
    assert session.events == ['submission', 'company', 'approval', 'billing', 'connection', 'configuration',
        'claim', 'reference', 'dialog', 'archive', 'validate', 'read_token', 'journal', 'discover', 'discard', 'release']
    payload, initial_poll = session.received[0]
    assert initial_poll is False
    assert (payload.forsendelse_id, payload.dialog_id) == (TRANSMISSION, DIALOG)
    assert payload.hovedskjema_xml == session.archive.previews[0].hovedskjema_xml
    assert payload.underskjema_xml == session.archive.previews[0].underskjema_xml
    assert all(name.startswith('source_') for name in payload.underskjema_xml)
    assert {name for name, _ in session.authority.calls} <= {'list', 'get'}


@pytest.mark.parametrize('change', ['history', 'overrides', 'withdrawals', 'claim', 'xml', 'confirmation-key', 'post-conflict'])
def test_retained_proof_failure_releases_owned_lease_before_credentials(change, monkeypatch):
    session = IndependentSession(); archive = session.archive
    if change == 'history': archive = replace(archive, source_history=None)
    if change == 'overrides': archive = replace(archive, overrides=None)
    if change == 'withdrawals': archive = replace(archive, withdrawal_capture_records=None)
    if change == 'claim': archive = replace(archive, source_submission_claims=())
    if change == 'xml': archive = replace(archive, previews=(replace(archive.previews[0], hovedskjema_xml='<changed/>'),))
    if change == 'confirmation-key':
        archive = replace_confirmation(archive, '{"dialogId":"wrong","dialogId":"' + DIALOG
            + '","forsendelseId":"' + TRANSMISSION + '"}')
    if change == 'post-conflict':
        event = archive.production_events[0]
        archive = replace(archive, production_events=(*archive.production_events,
            replace(event, id=str(UUID(int=98001)), operation_state='unknown', authority_reference=None,
                failure_class='unknown')))
    session.archive = archive
    instrument(monkeypatch, session)
    result = run(session)
    assert (result.state, result.error_code, result.requires_manual_retry) == ('processing', 'basis_unavailable', True)
    assert session.events[-2:] == ['validate', 'release']
    assert_no_effects(session)


@pytest.mark.parametrize('field', ['reference', 'dialog'])
@pytest.mark.parametrize('form', ['uppercase', 'braces', 'wrong-canonical'])
def test_original_reference_arguments_are_exact_not_normalized(field, form, monkeypatch):
    session = IndependentSession()
    value = getattr(session, field)
    if form == 'uppercase': changed = value.upper()
    elif form == 'braces': changed = '{' + value + '}'
    else: changed = str(UUID(int=98321))
    assert changed != value
    setattr(session, field, changed)
    instrument(monkeypatch, session)
    result = run(session)
    assert result.error_code == 'basis_unavailable'
    assert session.events[-2:] == ['validate', 'release']
    assert_no_effects(session)


@pytest.mark.parametrize('change', ['submission-actor', 'owner-role', 'approval-actor', 'connection-owner', 'organization'])
def test_identity_failures_keep_existing_precedence_and_effect_boundary(change, monkeypatch):
    session = IndependentSession()
    if change == 'submission-actor': session.submission = replace(session.submission, user_id=str(UUID(int=98101)))
    if change == 'owner-role': session.company.role = 'read_only'
    if change == 'approval-actor': session.approval = replace(session.approval, user_id=str(UUID(int=98101)))
    if change == 'connection-owner': session.connection = replace(session.connection, initiating_owner_user_id=str(UUID(int=98101)))
    if change == 'organization': session.company.org_number = '999999999'
    instrument(monkeypatch, session)
    result = run(session)
    assert result.error_code == ('connection_unavailable' if change == 'connection-owner' else 'basis_unavailable')
    assert result.state == (None if change == 'submission-actor' else 'processing')
    assert ('claim' in session.events) == (change == 'organization')
    assert ('release' in session.events) == (change == 'organization')
    if change == 'organization': assert session.events[-2:] == ['validate', 'release']
    assert_no_effects(session)


@pytest.mark.parametrize('mode', ['busy', 'raise-production', 'raise-unknown'])
def test_denied_or_ambiguous_claim_does_not_read_archive_or_release_unowned_lease(mode, monkeypatch):
    session = IndependentSession()
    session.archive = replace(session.archive, source_history=None)
    if mode == 'busy': session.busy = True
    else:
        session.failure_at = 'claim'
        if mode == 'raise-production': session.failure = rf.Rf1086ProductionError('status_busy')
    instrument(monkeypatch, session)
    result = run(session)
    assert result.error_code == ('status_unavailable' if mode == 'raise-unknown' else 'status_busy')
    assert session.events[-1] == 'claim'
    assert not any(name in session.events for name in ('reference', 'archive', 'validate', 'release'))
    assert_no_effects(session)


@pytest.mark.parametrize('stage', ['configuration', 'reference', 'dialog', 'archive', 'read_token', 'journal'])
def test_failures_preserve_error_classification_and_cleanup_stage(stage, monkeypatch):
    session = IndependentSession(); session.failure_at = stage
    if stage in ('configuration', 'reference', 'dialog'):
        session.failure = rf.Rf1086ProductionError('configuration_unavailable' if stage == 'configuration' else 'status_unavailable')
    instrument(monkeypatch, session)
    result = run(session)
    assert (result.state, result.error_code, result.requires_manual_retry) == (
        'processing', 'configuration_unavailable' if stage == 'configuration' else 'status_unavailable', True)
    assert ('release' in session.events) == (stage != 'configuration')
    assert ('discard' in session.events) == (stage == 'journal')
    assert not session.authority.calls
    if stage in ('configuration', 'reference', 'dialog', 'archive'): assert_no_effects(session)
    if stage == 'journal': assert session.events[-2:] == ['discard', 'release']


@pytest.mark.parametrize('stage', ['archive', 'read_token', 'discover'])
def test_cancellation_propagates_with_only_owned_cleanup(stage, monkeypatch):
    session = IndependentSession(); session.failure_at = stage; session.failure = asyncio.CancelledError()
    instrument(monkeypatch, session)
    with pytest.raises(asyncio.CancelledError): run(session)
    assert session.events.count('release') == 1
    assert session.events.count('discard') == (1 if stage == 'discover' else 0)
    assert session.events[-1] == 'release'
    if stage == 'archive': assert_no_effects(session)


@pytest.mark.parametrize('state', ['accepted', 'rejected'])
def test_terminal_result_never_validates_or_claims_even_if_retained_archive_is_bad(state, monkeypatch):
    session = IndependentSession(); session.submission = replace(session.submission, feedback_state=state)
    session.archive = replace(session.archive, source_history=None)
    instrument(monkeypatch, session)
    result = run(session)
    assert (result.state, result.error_code, result.requires_manual_retry) == (state, None, False)
    assert session.events == ['submission']
    assert_no_effects(session)


def test_stale_nonterminal_snapshot_selects_ancestor_not_new_child(monkeypatch):
    # Synthetic snapshot ordering only: SQL does not grant a fresh terminal-parent lease.
    session = IndependentSession(corrected(False))
    session.submission = replace(session.submission, feedback_state='processing')
    assert session.archive.production_submissions[0].feedback_state == 'accepted'
    assert session.archive.submission_head.submission_id.value != session.submission.id
    instrument(monkeypatch, session)
    result = run(session)
    assert result.error_code is None and result.state == 'accepted'
    payload, initial_poll = session.received[0]
    assert payload.submission_id == session.submission.id and initial_poll is False
    assert (payload.forsendelse_id, payload.dialog_id) == (session.reference, session.dialog)
    assert session.events[-2:] == ['discard', 'release']
