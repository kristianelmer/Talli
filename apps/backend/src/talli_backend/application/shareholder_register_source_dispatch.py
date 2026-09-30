"""Dispatch original full-year bytes through committed, currently admitted intents."""
from talli_backend.modules.billing.public import BillingSnapshotQuery
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear
from .shareholder_register_annual_readiness import read_annual_readiness
from .shareholder_register_source_admission import ShareholderRegisterSourceAdmission
from .shareholder_register_source_claim import ShareholderRegisterSourceClaimWorkflow
from .shareholder_register_filing_workflow import _valid_connection


@rf.rf1086_adapter(rf.Rf1086SourceOperationJournal)
class _AdmittedJournal:
    def __init__(self, session, admission, token, assessment, approval, completed, connection, correlation):
        self.session, self.admission, self.token = session, admission, token
        self.assessment, self.approval, self.completed = assessment, approval, completed
        self.connection, self.correlation = connection, correlation

    async def prepare(self, *, submission_id, name, body_hash, idempotency_key):
        claim = self.assessment.claim
        if submission_id != claim.submission_id.value:
            raise rf.Rf1086ProductionError('basis_unavailable')
        if name in self.completed:
            return rf.Rf1086SourceOperationPreparation(self.completed[name], False)
        expected = self.assessment.operation_id if name == self.assessment.pending_operation else None
        args = dict(operation_name=name, body_sha256=body_hash, idempotency_key=idempotency_key,
            connection=self.connection, expected_event_id=expected)
        if name == 'post_hovedskjema':
            async with self.admission.admit(self.token, company_id=claim.company_id, income_year=claim.income_year,
                    preview_id=rf.PreviewId(self.approval.preview_id), correlation_id=self.correlation) as admitted:
                if admitted.transaction.actor_id != self.session.actor_id:
                    raise rf.Rf1086ProductionError('basis_unavailable')
                annual = await read_annual_readiness(admitted, self.correlation)
                result = await admitted.transaction.prepare_source_operation(claim, annual=annual, **args)
        else:
            query = rf.Rf1086SourceQuery(claim.company_id, claim.income_year, self.session.actor_id)
            async with self.session.source_admission(query) as scope:
                identity = await scope.company_identity()
                if (scope.actor_id != self.session.actor_id
                        or identity.company.org_number != self.assessment.organization_number):
                    raise rf.Rf1086ProductionError('basis_unavailable')
                result = await scope.prepare_source_operation(claim, **args)
        # Exiting the context commits. A failed commit cannot return a send grant.
        return result

    async def finish(self, intent, *, state, reference, failure):
        return await self.session.finish_source_operation(self.assessment.claim.submission_id, intent.id,
            state=state, reference=reference, failure=failure)


class ShareholderRegisterSourceDispatchWorkflow:
    def __init__(self, sessions, documents):
        self._sessions = sessions
        self._claim = ShareholderRegisterSourceClaimWorkflow(sessions, documents)
        self._admission = ShareholderRegisterSourceAdmission(sessions, documents)

    async def position(self, access_token, *, approval_id):
        session = await self._sessions.session(access_token)
        retained = await session.read_source_claim_approval(approval_id)
        if retained is None:
            raise rf.ShareholderRegisterFilingError.not_found()
        query = rf.Rf1086ArchiveQuery(CompanyId(retained.approval.company_id),
            IncomeYear(retained.approval.income_year), session.actor_id)
        archive = await session.archive_source(query)
        return rf.inspect_rf1086_source_dispatch_position(archive, query=query, approval_id=approval_id)

    async def send(self, access_token, *, approval_id, manifest_sha256, expected_head=None, correlation_id):
        session = await self._sessions.session(access_token)
        session.require_configuration()
        claimed = await self._claim.claim(access_token, approval_id=approval_id,
            manifest_sha256=manifest_sha256, expected_head=expected_head, correlation_id=correlation_id)
        claim = claimed.claim
        query = rf.Rf1086ArchiveQuery(claim.company_id, claim.income_year, session.actor_id)
        archive = await session.archive_source(query)
        assessment = rf.assess_rf1086_source_dispatch(archive, query=query, submission_id=claim.submission_id)
        if assessment.claim != claim:
            raise rf.Rf1086ProductionError('basis_unavailable')
        if assessment.disposition == 'confirmed':
            return rf.Rf1086SendResult(claim.submission_id.value)
        if assessment.disposition == 'current_approval_required':
            raise rf.Rf1086ProductionError('payload_changed')
        if assessment.disposition == 'recovery_required':
            raise rf.Rf1086UnknownProductionOutcomeError(assessment.pending_operation)
        if assessment.disposition not in ('current_admission_required', 'retry_admission_required'):
            raise rf.Rf1086BlockedProductionOperationError(assessment.pending_operation)
        approval = next(row for row in archive.approvals if row.id == approval_id.value)
        company = await session.company_record(str(claim.company_id))
        snapshot = await session.billing.snapshot(BillingSnapshotQuery((claim.company_id,), session.actor_id, correlation_id))
        pilot = next((row for row in snapshot.pilot_entitlements if str(row.entitlement_id) == approval.entitlement_id), None)
        if (company is None or company.id != str(claim.company_id)
                or company.role != 'owner' or company.org_number != assessment.organization_number
                or pilot is None or str(pilot.company_id) != str(claim.company_id)
                or str(pilot.user_id) != str(session.actor_id.subject) or int(pilot.income_year) != int(claim.income_year)
                or str(pilot.obligation) != 'aksjonaerregisteroppgaven' or str(pilot.case_profile) != 'rf1086_full_year_v1'):
            raise rf.Rf1086ProductionError('basis_unavailable')
        connection = await session.read_connection(str(pilot.system_user_request_id), str(claim.company_id))
        if (not _valid_connection(connection, company_id=str(claim.company_id), actor_id=str(session.actor_id.subject),
                obligation='aksjonaerregisteroppgaven', external_ref=pilot.system_user_external_reference)
                or connection.id != str(pilot.system_user_request_id)):
            raise rf.Rf1086ProductionError('connection_unavailable')
        # The RF assessment already proved unique, ordered successes. Replaying
        # those rows skips completed work without rereading today's source bytes.
        completed = {event.operation_name: event for event in archive.production_events
            if event.submission_id == claim.submission_id.value and event.operation_state == 'succeeded'}
        binding = None
        try:
            binding = await session.bind_mutation_authority(company, connection)
            journal = _AdmittedJournal(session, self._admission, access_token, assessment,
                approval, completed, connection, correlation_id)
            await rf.execute_rf1086_source_dispatch(assessment.payload, journal=journal,
                read_journal=session.operation_journal(claim.submission_id.value), authority_client=binding.authority)
            return rf.Rf1086SendResult(claim.submission_id.value)
        finally:
            if binding is not None:
                binding.discard()
