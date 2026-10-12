"""Staged retained v3 review/approval; existing routes and grants are unchanged."""
from uuid import UUID

from talli_backend.application.shareholder_register_source_admission_v2 import ShareholderRegisterSourceAdmissionV2
from talli_backend.application.shareholder_register_source_approval import _entitlement, _hash
from talli_backend.application.shareholder_register_source_correction import ShareholderRegisterSourceCorrection
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, CorrelationId, IncomeYear


def _context(value, admitted, entitlement_id):
    if type(value) is not rf.Rf1086SourceApprovalContextV3:
        raise rf.Rf1086ProductionError('basis_unavailable')
    annual, review = value.annual_readiness, value.review
    rf.serialize_rf1086_retained_annual_readiness_v2(annual, admitted.source, admitted.retained_preview)
    if not (type(review) is rf.Rf1086SourceApprovalReview
            and review.company_id == admitted.source.company_id
            and review.income_year == admitted.source.income_year
            and review.preview_id == admitted.preview.preview_id
            and review.source_id == admitted.source.source_id
            and review.source_sha256 == admitted.source.source_sha256
            and review.entitlement_id == entitlement_id and _hash(review.review_sha256)
            and review.warning_codes == annual.required_warning_codes
            and type(review.blockers) is tuple
            and all(type(code) is str and bool(code.strip()) for code in review.blockers)
            and review.blockers == tuple(sorted(set(review.blockers)))
            and type(review.can_approve) is bool and review.can_approve == (not review.blockers)
            and (not review.can_approve or (admitted.preview.readiness_status == 'ready'
                and annual.readiness_status in ('ready','warning')))):
        raise rf.Rf1086ProductionError('basis_unavailable')
    return value


class ShareholderRegisterSourceApprovalV3:
    def __init__(self, sessions, documents):
        self._admission = ShareholderRegisterSourceAdmissionV2(sessions, documents)
        self._correction = ShareholderRegisterSourceCorrection(sessions, documents)

    async def read_review(self, access_token: str, *, company_id: CompanyId, income_year: IncomeYear,
            preview_id: rf.PreviewId, entitlement_id: str, correlation_id: CorrelationId):
        _entitlement(entitlement_id)
        async with self._admission.admit(access_token,company_id=company_id,income_year=income_year,
                preview_id=preview_id,correlation_id=correlation_id) as admitted:
            value = await admitted.transaction.read_source_approval_context_v3(preview_id,entitlement_id,correlation_id)
            return _context(value,admitted,entitlement_id)

    async def approve(self, access_token: str, *, company_id: CompanyId, income_year: IncomeYear,
            preview_id: rf.PreviewId, entitlement_id: str, review_sha256: str,
            acknowledged_warning_codes: tuple[str, ...], real_filing_confirmed: bool,
            predecessor: rf.Rf1086SourceCorrectionPredecessor | None = None, correlation_id: CorrelationId):
        _entitlement(entitlement_id)
        if (real_filing_confirmed is not True or not _hash(review_sha256)
                or type(acknowledged_warning_codes) is not tuple
                or any(type(code) is not str or not code.strip() for code in acknowledged_warning_codes)
                or len(set(acknowledged_warning_codes)) != len(acknowledged_warning_codes)
                or (predecessor is not None and type(predecessor) is not rf.Rf1086SourceCorrectionPredecessor)):
            raise rf.ShareholderRegisterFilingError.invalid_input()
        correction = None
        if predecessor is not None:
            correction = await self._correction.prepare(access_token,company_id=company_id,
                income_year=income_year,predecessor=predecessor)
        async with self._admission.admit(access_token,company_id=company_id,income_year=income_year,
                preview_id=preview_id,correlation_id=correlation_id) as admitted:
            transaction = admitted.transaction
            rf.assert_rf1086_submission_predecessor(await transaction.submission_history(),
                company_id=company_id,income_year=income_year,predecessor=predecessor)
            if correction is not None: await self._correction.assert_admitted(correction,transaction)
            observed = _context(await transaction.read_source_approval_context_v3(
                preview_id,entitlement_id,correlation_id),admitted,entitlement_id)
            review = observed.review
            if not review.can_approve: raise rf.Rf1086ProductionError('basis_unavailable')
            if review.review_sha256 != review_sha256 or set(acknowledged_warning_codes) != set(review.warning_codes):
                raise rf.Rf1086ProductionError('payload_changed')
            basis = rf.Rf1086SourceApprovalManifestBasisV3(admitted.source,admitted.preview,
                observed.annual_readiness,transaction.actor_id,entitlement_id,review.review_sha256,
                acknowledged_warning_codes,predecessor)
            manifest = rf.build_rf1086_retained_source_approval_manifest_v3(basis,admitted.retained_preview)
            result = await transaction.append_source_approval_v3(preview_id,entitlement_id,manifest,review_sha256,correlation_id)
            try:
                if (type(result) is not rf.Rf1086RecordedResult or result.company_id != company_id
                        or result.income_year != income_year or str(UUID(result.record_id)) != result.record_id):
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise rf.Rf1086ProductionError('basis_unavailable') from None
            return result
