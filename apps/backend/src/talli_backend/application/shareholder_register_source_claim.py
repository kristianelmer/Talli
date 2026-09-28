"""Claim exact approved source bytes under admission; no provider operations."""
import hashlib
import re
from uuid import UUID

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear
from .shareholder_register_source_admission import ShareholderRegisterSourceAdmission
from .shareholder_register_source_approval import _review
from .shareholder_register_source_correction import ShareholderRegisterSourceCorrection


class ShareholderRegisterSourceClaimWorkflow:
    def __init__(self,sessions,documents):
        self._sessions=sessions
        self._admission=ShareholderRegisterSourceAdmission(sessions,documents)
        self._correction=ShareholderRegisterSourceCorrection(sessions,documents)

    async def claim(self,access_token,*,approval_id,manifest_sha256,expected_head=None,correlation_id):
        try:
            if (not isinstance(approval_id,rf.ApprovalId) or str(UUID(approval_id.value))!=approval_id.value
                    or type(manifest_sha256) is not str or re.fullmatch('[a-f0-9]{64}',manifest_sha256) is None
                    or (expected_head is not None and (not isinstance(expected_head,rf.SubmissionId)
                        or str(UUID(expected_head.value))!=expected_head.value))):
                raise ValueError()
        except (ValueError,TypeError,AttributeError):
            raise rf.ShareholderRegisterFilingError.invalid_input() from None
        session=await self._sessions.session(access_token)
        async def recovered():
            existing=await session.read_source_submission_claim(approval_id,manifest_sha256,expected_head)
            if existing is None:return None
            rf.assert_rf1086_source_submission_claim(existing,approval_id=approval_id,
                manifest_sha256=manifest_sha256,expected_head=expected_head,actor_id=session.actor_id)
            return rf.Rf1086SourceSubmissionClaimResult(existing,False)
        existing=await recovered()
        if existing is not None:return existing
        try:
            retained=await session.read_source_claim_approval(approval_id)
            prior=rf.inspect_rf1086_retained_source_approval(retained,approval_id=approval_id,
                manifest_sha256=manifest_sha256,actor_id=session.actor_id)
            if (retained.approval.invalidated_at is not None
                    or (None if prior is None else prior.submission_id)!=expected_head):
                raise rf.Rf1086ProductionError('payload_changed')
            a=retained.approval;company_id=CompanyId(a.company_id);income_year=IncomeYear(a.income_year)
            correction=None if prior is None else await self._correction.prepare(access_token,
                company_id=company_id,income_year=income_year,predecessor=prior)
            async with self._admission.admit(access_token,company_id=company_id,income_year=income_year,
                    preview_id=rf.PreviewId(a.preview_id),correlation_id=correlation_id) as admitted:
                tx=admitted.transaction
                if tx.actor_id!=session.actor_id:raise rf.Rf1086ProductionError('basis_unavailable')
                existing=await tx.read_source_submission_claim(approval_id,manifest_sha256,expected_head)
                if existing is not None:
                    rf.assert_rf1086_source_submission_claim(existing,approval_id=approval_id,
                        manifest_sha256=manifest_sha256,expected_head=expected_head,actor_id=session.actor_id)
                    return rf.Rf1086SourceSubmissionClaimResult(existing,False)
                if await tx.read_source_claim_approval(approval_id)!=retained:
                    raise rf.Rf1086ProductionError('payload_changed')
                rf.assert_rf1086_submission_predecessor(await tx.submission_history(),
                    company_id=company_id,income_year=income_year,predecessor=prior)
                if correction is not None:await self._correction.assert_admitted(correction,tx)
                review=_review(await tx.read_source_approval_context(rf.PreviewId(a.preview_id),a.entitlement_id),admitted,a.entitlement_id)
                if not review.can_approve:raise rf.Rf1086ProductionError('basis_unavailable')
                rebuilt=rf.build_rf1086_source_approval_manifest(rf.Rf1086SourceApprovalManifestBasis(
                    admitted.source,admitted.preview,tx.actor_id,a.entitlement_id,review.review_sha256,review.warning_codes,prior))
                if (rf.serialize_rf1086_source_approval_manifest(rebuilt)!=retained.manifest_text
                        or rebuilt.manifest_sha256!=manifest_sha256
                        or hashlib.sha256(rf.serialize_rf1086_source_preview(admitted.preview).encode('utf-8')).hexdigest()!=a.payload_hash):
                    raise rf.Rf1086ProductionError('payload_changed')
                result=await tx.claim_source_submission(approval_id,manifest_sha256,expected_head)
                if not isinstance(result,rf.Rf1086SourceSubmissionClaimResult) or type(result.newly_claimed) is not bool:
                    raise rf.Rf1086ProductionError('basis_unavailable')
                rf.assert_rf1086_source_submission_claim(result.claim,approval_id=approval_id,
                    manifest_sha256=manifest_sha256,expected_head=expected_head,actor_id=session.actor_id)
                if (result.claim.company_id!=company_id or result.claim.income_year!=income_year
                        or result.claim.payload_sha256!=a.payload_hash):
                    raise rf.Rf1086ProductionError('basis_unavailable')
                return result
        except (rf.Rf1086ProductionError,rf.Rf1086YearSourceError,rf.ShareholderRegisterFilingError):
            # Another request may have committed during byte preflight or a
            # guard wait. Exact durable recovery never grants a new POST.
            existing=await recovered()
            if existing is not None:return existing
            raise
