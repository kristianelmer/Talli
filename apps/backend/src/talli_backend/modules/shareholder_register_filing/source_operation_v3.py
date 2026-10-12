"""Saved V3 operation correspondence only; live admission grants no escape."""
from . import public as rf
from .retained_readiness import parse_annual_binding


def inspect_identity(claim, retained, *, actor_id):
    """Bind an owned claim/header before original-byte preflight, never authority."""
    try:
        if type(claim) is not rf.Rf1086SourceSubmissionClaim:
            raise ValueError()
        rf.assert_rf1086_source_submission_claim(claim, approval_id=claim.approval_id,
            manifest_sha256=claim.manifest_sha256,
            expected_head=claim.predecessor_submission_id, actor_id=actor_id)
        predecessor = rf.inspect_rf1086_retained_source_approval_v3(retained,
            approval_id=claim.approval_id, manifest_sha256=claim.manifest_sha256, actor_id=actor_id)
        approval = retained.approval
        if (approval.company_id != str(claim.company_id)
                or approval.income_year != int(claim.income_year)
                or approval.payload_hash != claim.payload_sha256
                or (None if predecessor is None else predecessor.submission_id)
                    != claim.predecessor_submission_id):
            raise ValueError()
        return predecessor
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None


def assert_main_capture(claim, retained, source, capture, *, actor_id):
    """Rebuild the full saved manifest with existing retained policy and XML."""
    try:
        predecessor = inspect_identity(claim, retained, actor_id=actor_id)
        if (type(source) is not rf.Rf1086YearSourceSnapshotV2
                or type(capture) is not rf.Rf1086ArchiveSourcePreview
                or source.company_id != claim.company_id or source.income_year != claim.income_year
                or capture.preview.preview_id.value != retained.approval.preview_id
                or capture.payload_sha256 != claim.payload_sha256):
            raise ValueError()
        annual = parse_annual_binding(retained.approval.manifest['annualReadiness'], source,
            capture.preview, preview_payload_sha256=capture.payload_sha256,
            preview_payload_text=capture.payload_text)
        basis = rf.Rf1086SourceApprovalManifestBasisV3(source, capture.preview, annual, actor_id,
            retained.approval.entitlement_id, retained.approval.manifest['review']['sha256'],
            tuple(retained.approval.manifest['review']['acknowledgedWarningCodes']), predecessor)
        rebuilt = rf.build_rf1086_retained_source_approval_manifest_v3(basis, capture)
        if (rf.serialize_rf1086_source_approval_manifest_v3(rebuilt) != retained.manifest_text
                or rebuilt.manifest_sha256 != claim.manifest_sha256):
            raise rf.Rf1086ProductionError('payload_changed')
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError, RecursionError,
            rf.Rf1086YearSourceError, rf.ShareholderRegisterFilingError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None


def assert_claimed_history(claim, retained, history, *, actor_id):
    """Keep the complete predecessor chain while binding the already claimed leaf."""
    try:
        prior = inspect_identity(claim, retained, actor_id=actor_id)
        if type(history) is not tuple:
            raise ValueError()
        selected = tuple(row for row in history if row.id == claim.submission_id.value)
        if len(selected) != 1:
            raise ValueError()
        row = selected[0]
        if (type(row) is not rf.Rf1086ProductionSubmissionRecord
                or row.company_id != str(claim.company_id) or row.income_year != int(claim.income_year)
                or type(row.income_year) is not int or row.approval_id != claim.approval_id.value
                or row.entitlement_id != retained.approval.entitlement_id
                or row.user_id != str(actor_id.subject) or row.submitted_by != str(actor_id.subject)
                or row.payload_hash != claim.payload_sha256
                or row.supersedes_submission_id != (None if prior is None else prior.submission_id.value)
                or row.case_profile != 'rf1086_full_year_v1'
                or row.adapter_version != 'rf1086-source-production-v1'
                or row.obligation != 'aksjonaerregisteroppgaven' or row.environment != 'production'):
            raise ValueError()
        # Exclude only that exact owned committed leaf. No year, actor, profile,
        # status or timestamp filter may hide another row or competing successor.
        rf.assert_rf1086_submission_predecessor(tuple(item for item in history
            if item.id != claim.submission_id.value), company_id=claim.company_id,
            income_year=claim.income_year, predecessor=prior)
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None
