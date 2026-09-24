"""Review and approval of complete annual sources, without provider operations."""
import re
from uuid import UUID

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, CorrelationId, IncomeYear

from .shareholder_register_source_admission import ShareholderRegisterSourceAdmission


def _hash(value):
    return type(value) is str and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def _entitlement(value):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise rf.ShareholderRegisterFilingError.invalid_input() from None


def _review(value, admitted, entitlement_id):
    expected_warnings = tuple(sorted({issue.code for issue in admitted.preview.readiness_issues
                                     if issue.level == 'warning'}))
    if not (isinstance(value, rf.Rf1086SourceApprovalReview)
            and value.company_id == admitted.source.company_id
            and value.income_year == admitted.source.income_year
            and value.preview_id == admitted.preview.preview_id
            and value.source_id == admitted.source.source_id
            and value.source_sha256 == admitted.source.source_sha256
            and value.entitlement_id == entitlement_id and _hash(value.review_sha256)
            and value.warning_codes == expected_warnings
            and type(value.blockers) is tuple
            and all(type(code) is str and bool(code.strip()) for code in value.blockers)
            and value.blockers == tuple(sorted(set(value.blockers)))
            and type(value.can_approve) is bool and value.can_approve == (not value.blockers)
            and (not value.can_approve or admitted.preview.readiness_status == 'ready')):
        raise rf.Rf1086ProductionError('basis_unavailable')
    return value


class ShareholderRegisterSourceApprovalWorkflow:
    def __init__(self, sessions, documents):
        self._admission = ShareholderRegisterSourceAdmission(sessions, documents)

    async def read_review(self, access_token: str, *, company_id: CompanyId,
            income_year: IncomeYear, preview_id: rf.PreviewId, entitlement_id: str,
            correlation_id: CorrelationId) -> rf.Rf1086SourceApprovalReview:
        _entitlement(entitlement_id)
        async with self._admission.admit(access_token, company_id=company_id, income_year=income_year,
                preview_id=preview_id, correlation_id=correlation_id) as admitted:
            await admitted.transaction.bridge_source_preview(admitted.preview)
            return _review(await admitted.transaction.read_source_approval_context(preview_id, entitlement_id),
                           admitted, entitlement_id)

    async def approve(self, access_token: str, *, company_id: CompanyId,
            income_year: IncomeYear, preview_id: rf.PreviewId, entitlement_id: str,
            review_sha256: str, acknowledged_warning_codes: tuple[str, ...], real_filing_confirmed: bool,
            predecessor: rf.Rf1086SourceCorrectionPredecessor | None = None,
            correlation_id: CorrelationId) -> rf.Rf1086RecordedResult:
        _entitlement(entitlement_id)
        if (real_filing_confirmed is not True or not _hash(review_sha256)
                or type(acknowledged_warning_codes) is not tuple
                or any(type(code) is not str or not code.strip() for code in acknowledged_warning_codes)
                or len(set(acknowledged_warning_codes)) != len(acknowledged_warning_codes)):
            raise rf.ShareholderRegisterFilingError.invalid_input()
        async with self._admission.admit(access_token, company_id=company_id, income_year=income_year,
                preview_id=preview_id, correlation_id=correlation_id) as admitted:
            await admitted.transaction.bridge_source_preview(admitted.preview)
            review = _review(await admitted.transaction.read_source_approval_context(preview_id, entitlement_id),
                             admitted, entitlement_id)
            if not review.can_approve:
                raise rf.Rf1086ProductionError('basis_unavailable')
            if (review.review_sha256 != review_sha256
                    or set(acknowledged_warning_codes) != set(review.warning_codes)):
                raise rf.Rf1086ProductionError('payload_changed')
            basis = rf.Rf1086SourceApprovalManifestBasis(admitted.source, admitted.preview,
                admitted.transaction.actor_id, entitlement_id, review.review_sha256,
                acknowledged_warning_codes, predecessor)
            manifest = rf.build_rf1086_source_approval_manifest(basis)
            result = await admitted.transaction.append_source_approval(
                admitted.preview, entitlement_id, manifest, review.review_sha256)
            # A malformed owner projection rolls back with the same transaction.
            if (not isinstance(result, rf.Rf1086RecordedResult) or result.company_id != company_id
                    or result.income_year != income_year):
                raise rf.Rf1086ProductionError('basis_unavailable')
            try:
                if str(UUID(result.record_id)) != result.record_id:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise rf.Rf1086ProductionError('basis_unavailable') from None
            return result
