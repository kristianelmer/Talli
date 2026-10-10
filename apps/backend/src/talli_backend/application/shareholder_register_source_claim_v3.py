"""Closed V3 first claim and exact historical recovery; no provider operations."""
import hashlib
import re
from uuid import UUID

from talli_backend.application.shareholder_register_source_admission_v2 import ShareholderRegisterSourceAdmissionV2
from talli_backend.application.shareholder_register_source_approval_v3 import _context
from talli_backend.application.shareholder_register_source_correction import ShareholderRegisterSourceCorrection
from talli_backend.modules.company_access.public import CompanyAccessError
from talli_backend.modules.documents.public import DocumentsError
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear


def _identifiers(approval_id, manifest_sha256, expected_head):
    try:
        if (type(approval_id) is not rf.ApprovalId or str(UUID(approval_id.value)) != approval_id.value
                or type(manifest_sha256) is not str or re.fullmatch('[a-f0-9]{64}', manifest_sha256) is None
                or (expected_head is not None and (type(expected_head) is not rf.SubmissionId
                    or str(UUID(expected_head.value)) != expected_head.value))):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise rf.ShareholderRegisterFilingError.invalid_input() from None


class ShareholderRegisterSourceClaimV3:
    def __init__(self, sessions, documents):
        self._sessions = sessions
        self._admission = ShareholderRegisterSourceAdmissionV2(sessions, documents)
        self._correction = ShareholderRegisterSourceCorrection(sessions, documents)

    async def claim(self, access_token, *, approval_id, manifest_sha256, expected_head=None, correlation_id):
        _identifiers(approval_id, manifest_sha256, expected_head)
        session = await self._sessions.session(access_token)

        async def recovered(reader):
            existing = await reader.read_source_submission_claim(approval_id, manifest_sha256, expected_head)
            if existing is None:
                return None
            rf.assert_rf1086_source_submission_claim(existing, approval_id=approval_id,
                manifest_sha256=manifest_sha256, expected_head=expected_head, actor_id=session.actor_id)
            return rf.Rf1086SourceSubmissionClaimResult(existing, False)

        existing = await recovered(session)
        if existing is not None:
            return existing
        try:
            retained = await session.read_source_claim_approval_v3(approval_id)
            prior = rf.inspect_rf1086_retained_source_approval_v3(retained, approval_id=approval_id,
                manifest_sha256=manifest_sha256, actor_id=session.actor_id)
            approval = retained.approval
            company_id, income_year = CompanyId(approval.company_id), IncomeYear(approval.income_year)
            # Invalidation and current policy cannot deny a concurrent exact
            # claim before the historical guard's post-wait recovery lookup.
            correction = None if prior is None else await self._correction.prepare(access_token,
                company_id=company_id, income_year=income_year, predecessor=prior)
            prepared = await self._admission.prepare_preview(access_token, session,
                company_id=company_id, income_year=income_year, preview_id=rf.PreviewId(approval.preview_id))
            async with session.source_claim_recovery_v3(approval_id, manifest_sha256) as recovery:
                if recovery.actor_id != session.actor_id:
                    raise rf.Rf1086ProductionError('basis_unavailable')
                existing = await recovered(recovery)
                if existing is not None:
                    return existing
                if (await recovery.read_source_claim_approval_v3(approval_id) != retained
                        or approval.invalidated_at is not None
                        or (None if prior is None else prior.submission_id) != expected_head):
                    raise rf.Rf1086ProductionError('payload_changed')
                async with recovery.fresh_admission_v3() as transaction:
                    admitted = await self._admission.validate_held_preview(prepared, transaction, correlation_id)
                    rf.assert_rf1086_submission_predecessor(await transaction.submission_history(),
                        company_id=company_id, income_year=income_year, predecessor=prior)
                    if correction is not None:
                        await self._correction.assert_admitted(correction, transaction)
                    observed = _context(await transaction.read_source_approval_context_v3(
                        rf.PreviewId(approval.preview_id), approval.entitlement_id, correlation_id),
                        admitted, approval.entitlement_id)
                    if not observed.review.can_approve:
                        raise rf.Rf1086ProductionError('basis_unavailable')
                    basis = rf.Rf1086SourceApprovalManifestBasisV3(admitted.source, admitted.preview,
                        observed.annual_readiness, transaction.actor_id, approval.entitlement_id,
                        observed.review.review_sha256, observed.review.warning_codes, prior)
                    rebuilt = rf.build_rf1086_retained_source_approval_manifest_v3(basis, admitted.retained_preview)
                    if (rf.serialize_rf1086_source_approval_manifest_v3(rebuilt) != retained.manifest_text
                            or rebuilt.manifest_sha256 != manifest_sha256
                            or hashlib.sha256(rf.serialize_rf1086_source_preview(admitted.preview).encode()).hexdigest()
                                != approval.payload_hash):
                        raise rf.Rf1086ProductionError('payload_changed')
                    result = await transaction.claim_source_submission_v3(
                        approval_id, manifest_sha256, expected_head, correlation_id)
                    if type(result) is not rf.Rf1086SourceSubmissionClaimResult or type(result.newly_claimed) is not bool:
                        raise rf.Rf1086ProductionError('basis_unavailable')
                    rf.assert_rf1086_source_submission_claim(result.claim, approval_id=approval_id,
                        manifest_sha256=manifest_sha256, expected_head=expected_head, actor_id=session.actor_id)
                    if (result.claim.company_id != company_id or result.claim.income_year != income_year
                            or result.claim.payload_sha256 != approval.payload_hash):
                        raise rf.Rf1086ProductionError('basis_unavailable')
                    return result
        except (rf.Rf1086ProductionError, rf.Rf1086YearSourceError,
                rf.ShareholderRegisterFilingError, DocumentsError, CompanyAccessError):
            existing = await recovered(session)
            if existing is not None:
                return existing
            raise
