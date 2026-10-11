"""Closed V3 dispatch construction; no route, runtime grant or provider effect."""
from dataclasses import dataclass

from talli_backend.application.shareholder_register_source_claim_v3 import (
    ShareholderRegisterSourceClaimV3, _identifiers)
from talli_backend.application.shareholder_register_filing_workflow import _valid_connection
from talli_backend.modules.billing.public import BillingSnapshotQuery
from talli_backend.modules.company_access.public import CompanyAccessError
from talli_backend.modules.documents.public import DocumentsError
from talli_backend.application.shareholder_register_source_admission_v2 import (
    PreparedRf1086SourceAdmissionV2, ShareholderRegisterSourceAdmissionV2)
from talli_backend.application.shareholder_register_source_correction import (
    ShareholderRegisterSourceCorrection, VerifiedRf1086Correction)
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear


_ADMISSION_DENIALS = (rf.Rf1086ProductionError, rf.Rf1086YearSourceError,
    rf.ShareholderRegisterFilingError, DocumentsError, CompanyAccessError)


class _ConfirmedOperationHistory(Exception):
    """Internal control flow: complete retained history requires no provider call."""


def _require_fresh_disposition(assessment):
    if assessment.disposition == 'confirmed':
        raise _ConfirmedOperationHistory()
    if assessment.disposition == 'recovery_required':
        raise rf.Rf1086UnknownProductionOutcomeError(assessment.pending_operation)
    if assessment.disposition == 'current_approval_required':
        raise rf.Rf1086ProductionError('payload_changed')
    if assessment.disposition not in ('current_admission_required', 'retry_admission_required'):
        raise rf.Rf1086BlockedProductionOperationError(assessment.pending_operation)


@rf.rf1086_adapter(rf.Rf1086SourceOperationJournal)
class _OperationJournalV3:
    def __init__(self, workflow, session, token, claim, connection, correlation_id, prepared_main=None):
        self._workflow, self._session, self._token = workflow, session, token
        self._claim, self._connection, self._correlation_id = claim, connection, correlation_id
        self._prepared_main = prepared_main

    async def _historical_preparation(self, historical, name, body_hash):
        observed = await historical.read_operation_recovery()
        _require_fresh_disposition(observed.assessment)
        completed = next((event for event in observed.retained_archive.production_events
            if event.submission_id == self._claim.submission_id.value
                and event.operation_name == name and event.operation_state == 'succeeded'), None)
        if completed is not None:
            if completed.body_hash != body_hash:
                raise rf.Rf1086ProductionError('basis_unavailable')
            return observed, rf.Rf1086SourceOperationPreparation(completed, False)
        if name != observed.assessment.pending_operation:
            raise rf.Rf1086ProductionError('basis_unavailable')
        return observed, None

    async def prepare(self, *, submission_id, name, body_hash, idempotency_key):
        claim = self._claim
        if submission_id != claim.submission_id.value:
            raise rf.Rf1086ProductionError('basis_unavailable')
        prepared = None
        try:
            # Check history before main object I/O. Release the historical
            # guard before any byte preflight, then recheck after reacquiring.
            async with self._session.source_operation_recovery_v3(claim) as historical:
                observed, completed = await self._historical_preparation(historical, name, body_hash)
                if completed is not None:
                    return completed
            if name == 'post_hovedskjema':
                approval = next(row for row in observed.retained_archive.approvals
                    if row.id == claim.approval_id.value)
                lineage = next(row for row in observed.retained_archive.source_approval_lineage
                    if row.approval_id == approval.id)
                prepared = self._prepared_main
                if prepared is None:
                    prepared = await self._workflow.prepare_main_intent_v3(self._token, self._session,
                        claim=claim, retained=rf.Rf1086RetainedSourceApproval(approval, lineage.manifest_text),
                        correlation_id=self._correlation_id)
            async with self._session.source_operation_recovery_v3(claim) as historical:
                observed, completed = await self._historical_preparation(historical, name, body_hash)
                if completed is not None:
                    return completed
                async with historical.fresh_operation_admission_v3() as fresh:
                    args = dict(idempotency_key=idempotency_key,
                        expected_event_id=observed.assessment.operation_id, connection=self._connection,
                        correlation_id=self._correlation_id)
                    if name == 'post_hovedskjema':
                        await self._workflow.validate_held_main_intent_v3(prepared, fresh, self._correlation_id)
                        result = await fresh.prepare_main_operation_v3(prepared, **args)
                        if result.event.body_hash != body_hash:
                            raise rf.Rf1086ProductionError('basis_unavailable')
                    elif name.startswith('post_underskjema:'):
                        result = await fresh.prepare_child_operation_v3(claim,
                            document_name='underskjema_' + name[len('post_underskjema:'):],
                            body_sha256=body_hash, **args)
                    elif name == 'confirm':
                        result = await fresh.prepare_confirm_operation_v3(claim,
                            body_sha256=body_hash, **args)
                    else:
                        raise rf.Rf1086ProductionError('basis_unavailable')
            # Only this return occurs after both context exits and commit.
            return result
        except _ADMISSION_DENIALS:
            # Failed current scope is already closed. A separate historical
            # read can recover a concurrent success; it cannot create a grant.
            async with self._session.source_operation_recovery_v3(claim) as historical:
                _, completed = await self._historical_preparation(historical, name, body_hash)
            if completed is not None:
                return completed
            raise

    async def finish(self, intent, *, state, reference, failure):
        return await self._session.finish_source_operation(self._claim.submission_id, intent.id,
            state=state, reference=reference, failure=failure)


@dataclass(frozen=True, slots=True)
class PreparedRf1086MainOperationV3:
    """Original-byte verification data; no annual proof, live scope or authority."""
    claim: rf.Rf1086SourceSubmissionClaim
    retained: rf.Rf1086RetainedSourceApproval
    preview: PreparedRf1086SourceAdmissionV2
    correction: VerifiedRf1086Correction | None


class ShareholderRegisterSourceDispatchV3:
    def __init__(self, sessions, documents):
        self._sessions = sessions
        self._documents = documents
        self._claim = ShareholderRegisterSourceClaimV3(sessions, documents)
        self._admission = ShareholderRegisterSourceAdmissionV2(sessions, documents)
        self._correction = ShareholderRegisterSourceCorrection(sessions, documents)

    async def prepare_main_intent_v3(self, access_token, session, *, claim, retained, correlation_id):
        predecessor = rf.inspect_rf1086_source_operation_identity_v3(claim, retained,
            actor_id=session.actor_id)
        # Re-establish owned inputs before object I/O. This is an ordinary read,
        # not a new admission or permission to dispatch the supplied identity.
        if (await session.read_source_submission_claim(claim.approval_id,
                claim.manifest_sha256, claim.predecessor_submission_id) != claim
                or await session.read_source_claim_approval_v3(claim.approval_id) != retained):
            raise rf.Rf1086ProductionError('basis_unavailable')
        if self._documents is None:
            raise rf.Rf1086ProductionError('basis_unavailable')
        correction = None if predecessor is None else await self._correction.prepare_claimed_operation_v3(access_token,
            claim=claim, retained=retained)
        if predecessor is not None and (type(correction) is not VerifiedRf1086Correction
                or correction.company_id != claim.company_id or correction.income_year != claim.income_year
                or correction.actor_id != session.actor_id or correction.predecessor != predecessor):
            raise rf.Rf1086ProductionError('basis_unavailable')
        preview = await self._admission.prepare_preview(access_token, session,
            company_id=claim.company_id, income_year=claim.income_year,
            preview_id=rf.PreviewId(retained.approval.preview_id))
        rf.assert_rf1086_source_main_preflight_v3(claim, retained, preview.source,
            preview.retained_preview, actor_id=session.actor_id)
        return PreparedRf1086MainOperationV3(claim, retained, preview, correction)

    async def validate_held_main_intent_v3(self, prepared, transaction, correlation_id):
        """Reuse the configured validators on the existing scope; no object I/O."""
        if (type(prepared) is not PreparedRf1086MainOperationV3
                or type(prepared.preview) is not PreparedRf1086SourceAdmissionV2):
            raise rf.Rf1086ProductionError('basis_unavailable')
        predecessor = rf.inspect_rf1086_source_operation_identity_v3(prepared.claim,
            prepared.retained, actor_id=transaction.actor_id)
        if predecessor is not None:
            correction = prepared.correction
            if (type(correction) is not VerifiedRf1086Correction
                    or correction.company_id != prepared.claim.company_id
                    or correction.income_year != prepared.claim.income_year
                    or correction.actor_id != transaction.actor_id or correction.predecessor != predecessor):
                raise rf.Rf1086ProductionError('basis_unavailable')
            await self._correction.assert_claimed_operation_admitted_v3(correction, transaction,
                claim=prepared.claim, retained=prepared.retained)
        elif prepared.correction is not None:
            raise rf.Rf1086ProductionError('basis_unavailable')
        return await self._admission.validate_held_preview(
            prepared.preview, transaction, correlation_id)

    async def position(self, access_token, *, approval_id):
        session = await self._sessions.session(access_token)
        retained = await session.read_source_operation_approval_v3(approval_id)
        if retained is None:
            raise rf.ShareholderRegisterFilingError.not_found()
        query = rf.Rf1086ArchiveQuery(CompanyId(retained.approval.company_id),
            IncomeYear(retained.approval.income_year), session.actor_id)
        archive = await session.archive_source(query)
        return rf.inspect_rf1086_retained_source_dispatch_position(archive, query=query, approval_id=approval_id)

    async def _claim_for_dispatch_v3(self, access_token, session, *, approval_id,
            manifest_sha256, expected_head, correlation_id):
        claim = await session.read_source_submission_claim(approval_id, manifest_sha256, expected_head)
        if claim is not None:
            return claim
        try:
            retained = await session.read_source_operation_approval_v3(approval_id)
            rf.inspect_rf1086_retained_source_approval_v3(retained, approval_id=approval_id,
                manifest_sha256=manifest_sha256, actor_id=session.actor_id)
            if self._documents is None:
                raise rf.Rf1086ProductionError('basis_unavailable')
            return (await self._claim.claim(access_token, approval_id=approval_id,
                manifest_sha256=manifest_sha256, expected_head=expected_head,
                correlation_id=correlation_id)).claim
        except _ADMISSION_DENIALS:
            # Header generation/configuration can race an exact committed
            # claim too. Reuse the existing historical owner/company/year
            # guard; this branch cannot create a first claim or a send grant.
            async with session.source_claim_recovery_v3(approval_id, manifest_sha256) as recovery:
                claim = await recovery.read_source_submission_claim(
                    approval_id, manifest_sha256, expected_head)
            if claim is not None:
                return claim
            raise

    async def send(self, access_token, *, approval_id, manifest_sha256, expected_head=None, correlation_id):
        _identifiers(approval_id, manifest_sha256, expected_head)
        session = await self._sessions.session(access_token)
        claim = await self._claim_for_dispatch_v3(access_token, session, approval_id=approval_id,
            manifest_sha256=manifest_sha256, expected_head=expected_head, correlation_id=correlation_id)
        rf.assert_rf1086_source_submission_claim(claim, approval_id=approval_id,
            manifest_sha256=manifest_sha256, expected_head=expected_head, actor_id=session.actor_id)
        binding = None
        try:
            async with session.source_operation_recovery_v3(claim) as historical:
                observed = await historical.read_operation_recovery()
                _require_fresh_disposition(observed.assessment)
            approval = next(row for row in observed.retained_archive.approvals
                if row.id == approval_id.value)
            prepared_main = None
            if observed.assessment.pending_operation == 'post_hovedskjema':
                lineage = next(row for row in observed.retained_archive.source_approval_lineage
                    if row.approval_id == approval.id)
                prepared_main = await self.prepare_main_intent_v3(access_token, session,
                    claim=claim, retained=rf.Rf1086RetainedSourceApproval(approval, lineage.manifest_text),
                    correlation_id=correlation_id)
            session.require_configuration()
            company = await session.company_record(str(claim.company_id))
            snapshot = await session.billing.snapshot(BillingSnapshotQuery(
                (claim.company_id,), session.actor_id, correlation_id))
            pilot = next((row for row in snapshot.pilot_entitlements
                if str(row.entitlement_id) == approval.entitlement_id), None)
            if (company is None or company.id != str(claim.company_id) or company.role != 'owner'
                    or company.org_number != observed.assessment.organization_number
                    or pilot is None or str(pilot.company_id) != str(claim.company_id)
                    or str(pilot.user_id) != str(session.actor_id.subject)
                    or int(pilot.income_year) != int(claim.income_year)
                    or str(pilot.obligation) != 'aksjonaerregisteroppgaven'
                    or str(pilot.case_profile) != 'rf1086_full_year_v1'):
                raise rf.Rf1086ProductionError('basis_unavailable')
            connection = await session.read_connection(str(pilot.system_user_request_id), str(claim.company_id))
            if (not _valid_connection(connection, company_id=str(claim.company_id),
                    actor_id=str(session.actor_id.subject), obligation='aksjonaerregisteroppgaven',
                    external_ref=pilot.system_user_external_reference)
                    or connection.id != str(pilot.system_user_request_id)):
                raise rf.Rf1086ProductionError('connection_unavailable')
            binding = await session.bind_mutation_authority(company, connection)
            journal = _OperationJournalV3(self, session, access_token, claim, connection, correlation_id, prepared_main)
            await rf.execute_rf1086_source_dispatch(observed.assessment.payload, journal=journal,
                read_journal=session.operation_journal(claim.submission_id.value), authority_client=binding.authority)
            return rf.Rf1086SendResult(claim.submission_id.value)
        except _ConfirmedOperationHistory:
            return rf.Rf1086SendResult(claim.submission_id.value)
        except _ADMISSION_DENIALS:
            async with session.source_operation_recovery_v3(claim) as historical:
                recovered = await historical.read_operation_recovery()
            if recovered.assessment.disposition == 'confirmed':
                return rf.Rf1086SendResult(claim.submission_id.value)
            _require_fresh_disposition(recovered.assessment)
            raise
        finally:
            if binding is not None:
                binding.discard()
