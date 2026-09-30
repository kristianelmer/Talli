"""RF source readiness, deliberately separate from annual and release admission.

The pure builder verifies retained integrity and canonical rendering. The
application admission scope supplies currentness; a digest is not authorization.
No historical source-facts or production manifest hash algorithm changes here.
"""
import hashlib

from . import public as rf


# These prerequisites are not inferred from source confirmations or XML. Their
# owning public contracts must be consumed independently before release.
NOT_EVALUATED = (
    "annual_prerequisites",
    "current_review_comments",
    "filing_overrides",
    "authority_permission",
    "billing_entitlement",
    "technical_release",
    "warning_acknowledgements",
)


def build(source: rf.Rf1086YearSourceSnapshot,
          preview: rf.Rf1086SourcePreview) -> rf.Rf1086SourceReadinessProof:
    rf.assert_rf1086_year_source_integrity(source)
    rf.assert_rf1086_source_preview_matches(preview, source)
    evidence = rf.Rf1086SourceReadinessEvidence(
        company_id=source.company_id, income_year=source.income_year,
        source_id=source.source_id, source_version=source.version,
        source_sha256=source.source_sha256, case_sha256=source.case_sha256,
        freshness=source.freshness, preview_id=preview.preview_id,
        preview_payload_sha256=hashlib.sha256(
            rf.serialize_rf1086_source_preview(preview).encode("utf-8")).hexdigest(),
        rendering_profile=preview.rendering_profile,
    )
    content = {"schema_version": "rf1086-source-readiness-v1", "evidence": evidence,
               "readiness_status": preview.readiness_status, "issues": preview.readiness_issues,
               "not_evaluated": NOT_EVALUATED}
    return rf.Rf1086SourceReadinessProof(
        evidence=evidence, readiness_status=preview.readiness_status,
        issues=preview.readiness_issues, not_evaluated=NOT_EVALUATED,
        proof_sha256=rf.rf1086_year_source_digest(content))


def assert_matches(proof: rf.Rf1086SourceReadinessProof,
                   source: rf.Rf1086YearSourceSnapshot,
                   preview: rf.Rf1086SourcePreview) -> None:
    """Reject altered evidence, scope or assessment; never assert currentness."""
    expected = build(source, preview)
    try:
        if (not isinstance(proof, rf.Rf1086SourceReadinessProof)
                or rf.rf1086_year_source_digest(proof) != rf.rf1086_year_source_digest(expected)):
            raise ValueError()
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        raise rf.Rf1086YearSourceError("rf1086_source_readiness_mismatch") from None
