"""Bind RF commands to a verified owner and the single production journal."""
from __future__ import annotations

import re
from uuid import uuid4

from talli_backend.application.shareholder_register_filing_session import AuthenticatedShareholderRegisterFilingSession
from talli_backend.modules.billing.public import BillingEntitlementQuery, BillingObligation, BillingSnapshotQuery
from talli_backend.modules.shareholder_register_filing.public import (
    AcknowledgeRf1086ReviewCommentCommand, AddRf1086ReviewCommentCommand, ApproveRf1086ProductionCommand,
    ConfirmRf1086FilingPermissionCommand, ConfirmRf1086SimulationCommand, GenerateRf1086PreviewCommand,
    JournaledRf1086ProductionInput, ReconcileRf1086FeedbackCommand, RecordRf1086OverrideCommand,
    RecordRf1086TestEvidenceCommand, Rf1086OwnerReconciliationResult, Rf1086RecordedResult,
    ReadRf1086PreviewQuery, Rf1086PreviewRecord, Rf1086SourceFacts, Rf1086SourceQuery, Rf1086WorkspaceQuery, Rf1086WorkspaceSnapshot,
    VerifyRf1086SourceEvidenceQuery, create_rf1086_preparation_service,
    execute_journaled_rf1086_production, rf1086_current_manifest_hash, rf1086_production_document_order,
    reconcile_journaled_rf1086_production,
    Rf1086ProductionError, Rf1086ReconciliationInput, Rf1086SendResult, SendApprovedRf1086Command,
)
from talli_backend.shared.kernel import ActorId, CompanyId, CorrelationId, IncomeYear


def _required_uuid_identity(value: str) -> str:
    from uuid import UUID
    try:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", value):
            raise ValueError()
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise Rf1086ProductionError("invalid_request") from None


def _valid_connection(connection, *, company_id: str, actor_id: str, obligation: str, external_ref: str) -> bool:
    return (connection is not None and connection.company_id == company_id
        and connection.initiating_owner_user_id == actor_id and connection.obligation == obligation
        and connection.status == "accepted" and connection.preflight_verified and connection.external_ref == external_ref)


async def send_approved_rf1086_production_filing(session: AuthenticatedShareholderRegisterFilingSession, approval_id: str) -> Rf1086SendResult:
    approval_id = _required_uuid_identity(approval_id)
    session.require_configuration()
    actor = str(session.actor_id.subject)
    approval = await session.read_approval(approval_id)
    if approval is None or approval.invalidated:
        raise Rf1086ProductionError("approval_expired")
    await session.require_fresh_production_owner(approval.company_id)
    preview = await session.read_preview(approval.preview_id)
    correlation = CorrelationId(str(uuid4()))
    snapshot = await session.billing.snapshot(BillingSnapshotQuery((CompanyId(approval.company_id),), session.actor_id, correlation))
    decision = await session.billing.entitlement(BillingEntitlementQuery(CompanyId(approval.company_id), session.actor_id,
        correlation, IncomeYear(approval.income_year), BillingObligation.SHAREHOLDER_REGISTER, "rf1086_no_activity_v1"))
    company = await session.company_record(approval.company_id)
    entitlement = next((candidate for candidate in snapshot.pilot_entitlements if str(candidate.entitlement_id) == approval.entitlement_id), None)
    if (preview is None or entitlement is None or company is None or str(entitlement.user_id) != actor
            or not decision.allowed or str(decision.pilot_entitlement_id) != str(entitlement.entitlement_id)
            or not preview.hovedskjema_xml):
        raise Rf1086ProductionError("basis_unavailable")
    connection = await session.read_connection(str(entitlement.system_user_request_id), approval.company_id)
    if not _valid_connection(connection, company_id=approval.company_id, actor_id=actor,
                             obligation=approval.obligation, external_ref=entitlement.system_user_external_reference):
        raise Rf1086ProductionError("connection_unavailable")
    document_order = rf1086_production_document_order(preview)
    if (approval.manifest is None or not re.fullmatch(r"[a-f0-9]{64}", approval.manifest_hash)
        or rf1086_current_manifest_hash(preview, actor_id=actor, organization_number=company.org_number,
            approved_manifest=approval.manifest) != approval.manifest_hash):
        raise Rf1086ProductionError("payload_changed")
    binding = None
    try:
        binding = await session.bind_mutation_authority(company, connection)
        submission_id = await session.begin_production_filing(approval.id)
        submitted = await execute_journaled_rf1086_production(JournaledRf1086ProductionInput(
            submission_id, preview.income_year, preview.hovedskjema_xml, preview.underskjema_xml, document_order),
            journal=session.operation_journal(submission_id), authority_client=binding.authority)
        lease_id = str(uuid4())
        if await session.claim_feedback_lease(submission_id, lease_id):
            try:
                reference = await session.read_claimed_reference(submission_id, lease_id)
                if reference != submitted.forsendelse_id:
                    raise Rf1086ProductionError("send_unavailable")
                await reconcile_journaled_rf1086_production(session.feedback_journal(submission_id=submission_id,
                    company_id=approval.company_id, income_year=preview.income_year, forsendelse_id=reference, lease_id=lease_id),
                    binding.read_only_authority, Rf1086ReconciliationInput(submission_id, approval.company_id,
                        preview.income_year, reference, preview.hovedskjema_xml, preview.underskjema_xml), initial_poll=True)
            finally:
                await session.release_feedback_lease(submission_id, lease_id)
        return Rf1086SendResult(submission_id)
    except Exception:
        raise Rf1086ProductionError("send_unavailable") from None
    finally:
        if binding is not None:
            binding.discard()


async def reconcile_rf1086_production(session: AuthenticatedShareholderRegisterFilingSession, submission_id: str) -> Rf1086OwnerReconciliationResult:
    state = None
    binding = None
    claimed = False
    lease_id = str(uuid4())
    try:
        submission_id = _required_uuid_identity(submission_id)
        actor = str(session.actor_id.subject)
        submission = await session.read_submission(submission_id)
        if (submission is None or submission.user_id != actor or submission.obligation != "aksjonaerregisteroppgaven"
                or submission.case_profile != "rf1086_no_activity_v1" or submission.environment != "production"):
            raise Rf1086ProductionError("basis_unavailable")
        state = submission.feedback_state
        if state in {"accepted", "rejected", "action_required"}:
            return Rf1086OwnerReconciliationResult(state)
        company = await session.company_record(submission.company_id)
        approval = await session.read_approval(submission.approval_id)
        snapshot = await session.billing.snapshot(BillingSnapshotQuery((CompanyId(submission.company_id),),
            session.actor_id, CorrelationId(str(uuid4()))))
        entitlement = next((candidate for candidate in snapshot.pilot_entitlements if str(candidate.entitlement_id) == submission.entitlement_id), None)
        if (company is None or company.role != "owner" or approval is None or entitlement is None
            or approval.company_id != submission.company_id or approval.user_id != actor
            or approval.entitlement_id != str(entitlement.entitlement_id) or approval.income_year != submission.income_year
            or approval.obligation != submission.obligation or approval.case_profile != submission.case_profile
            or str(entitlement.company_id) != submission.company_id or str(entitlement.user_id) != actor
            or int(entitlement.income_year) != submission.income_year or str(entitlement.obligation) != submission.obligation
            or str(entitlement.case_profile) != submission.case_profile):
            raise Rf1086ProductionError("basis_unavailable")
        connection = await session.read_connection(str(entitlement.system_user_request_id), submission.company_id)
        preview = await session.read_preview(approval.preview_id)
        if (not _valid_connection(connection, company_id=submission.company_id, actor_id=actor,
                obligation=submission.obligation, external_ref=entitlement.system_user_external_reference)
            or preview is None or preview.company_id != submission.company_id or preview.income_year != submission.income_year
            or not preview.hovedskjema_xml):
            raise Rf1086ProductionError("connection_unavailable")
        session.require_configuration()
        claimed = await session.claim_feedback_lease(submission.id, lease_id)
        if not claimed:
            raise Rf1086ProductionError("status_busy")
        reference = await session.read_claimed_reference(submission.id, lease_id)
        binding = await session.bind_read_only_authority(company, connection)
        result = await reconcile_journaled_rf1086_production(session.feedback_journal(submission_id=submission.id,
            company_id=submission.company_id, income_year=submission.income_year, forsendelse_id=reference, lease_id=lease_id),
            binding.authority, Rf1086ReconciliationInput(submission.id, submission.company_id, submission.income_year,
                reference, preview.hovedskjema_xml, preview.underskjema_xml), initial_poll=False)
        return Rf1086OwnerReconciliationResult(result.state)
    except Rf1086ProductionError as error:
        return Rf1086OwnerReconciliationResult(state, error.code, True)
    except Exception:
        return Rf1086OwnerReconciliationResult(state, "status_unavailable", True)
    finally:
        if binding is not None:
            binding.discard()
        if claimed:
            await session.release_feedback_lease(submission_id, lease_id)


class ShareholderRegisterFilingWorkflow:
    def __init__(self, persistence: AuthenticatedShareholderRegisterFilingSession) -> None:
        self._persistence = persistence

    @property
    def actor_id(self) -> ActorId:
        return self._persistence.actor_id

    def _actor(self, actor_id: ActorId) -> None:
        if actor_id != self._persistence.actor_id:
            raise Rf1086ProductionError("authentication_required")

    async def send_approved_filing(self, command: SendApprovedRf1086Command) -> Rf1086SendResult:
        self._actor(command.actor_id)
        return await send_approved_rf1086_production_filing(self._persistence, str(command.approval_id))

    async def reconcile_feedback(self, command: ReconcileRf1086FeedbackCommand) -> Rf1086OwnerReconciliationResult:
        self._actor(command.actor_id)
        return await reconcile_rf1086_production(self._persistence, str(command.submission_id))

    async def generate_preview(self, command: GenerateRf1086PreviewCommand) -> Rf1086RecordedResult:
        self._actor(command.actor_id)
        return await create_rf1086_preparation_service(self._persistence).generate_preview(command)

    async def record_override(self, command: RecordRf1086OverrideCommand) -> Rf1086RecordedResult:
        self._actor(command.actor_id)
        return await create_rf1086_preparation_service(self._persistence).record_override(command)

    async def add_review_comment(self, command: AddRf1086ReviewCommentCommand) -> Rf1086RecordedResult:
        self._actor(command.actor_id)
        return await create_rf1086_preparation_service(self._persistence).add_review_comment(command)

    async def acknowledge_review_comment(self, command: AcknowledgeRf1086ReviewCommentCommand) -> Rf1086RecordedResult:
        self._actor(command.actor_id)
        return await create_rf1086_preparation_service(self._persistence).acknowledge_review_comment(command)

    async def confirm_simulation(self, command: ConfirmRf1086SimulationCommand) -> Rf1086RecordedResult:
        self._actor(command.actor_id)
        return await create_rf1086_preparation_service(self._persistence).confirm_simulation(command)

    async def confirm_filing_permission(self, command: ConfirmRf1086FilingPermissionCommand) -> Rf1086RecordedResult:
        self._actor(command.actor_id)
        return await create_rf1086_preparation_service(self._persistence).confirm_filing_permission(command)

    async def record_test_evidence(self, command: RecordRf1086TestEvidenceCommand) -> Rf1086RecordedResult:
        self._actor(command.actor_id)
        return await create_rf1086_preparation_service(self._persistence).record_test_evidence(command)

    async def approve_production(self, command: ApproveRf1086ProductionCommand) -> Rf1086RecordedResult:
        self._actor(command.actor_id)
        return await create_rf1086_preparation_service(self._persistence).approve_production(command)

    async def workspace(self, query: Rf1086WorkspaceQuery) -> Rf1086WorkspaceSnapshot:
        self._actor(query.actor_id)
        return await create_rf1086_preparation_service(self._persistence).workspace(query)

    async def source_facts(self, query: Rf1086SourceQuery) -> Rf1086SourceFacts:
        self._actor(query.actor_id)
        return await create_rf1086_preparation_service(self._persistence).source_facts(query)

    async def verify_source_evidence(self, query: VerifyRf1086SourceEvidenceQuery) -> bool:
        self._actor(query.query.actor_id)
        return await create_rf1086_preparation_service(self._persistence).verify_source_evidence(query)

    async def read_preview(self, query: ReadRf1086PreviewQuery) -> Rf1086PreviewRecord | None:
        self._actor(query.actor_id)
        return await create_rf1086_preparation_service(self._persistence).read_preview(query)


__all__ = ["ShareholderRegisterFilingWorkflow"]
