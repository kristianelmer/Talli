"""Pure v2 source commitments; no mutable evidence or release authorization."""
import hashlib

from . import public as rf
from .source_readiness import NOT_EVALUATED
from .readiness_shape_v2 import matches_shape


def build(source: rf.Rf1086YearSourceSnapshotV2,
          preview: rf.Rf1086SourcePreview) -> rf.Rf1086SourceReadinessProofV2:
    rf.assert_rf1086_year_source_integrity_v2(source)
    rf.assert_rf1086_source_preview_matches(preview, source)
    evidence = rf.Rf1086SourceReadinessEvidenceV2(
        company_id=source.company_id, income_year=source.income_year,
        source_id=source.source_id, source_version=source.version,
        source_sha256=source.source_sha256, case_sha256=source.case_sha256,
        freshness=source.freshness, preview_id=preview.preview_id,
        preview_payload_sha256=hashlib.sha256(
            rf.serialize_rf1086_source_preview(preview).encode('utf-8')).hexdigest(),
        rendering_profile=preview.rendering_profile,
    )
    content = dict(schema_version='rf1086-source-readiness-v2', evidence=evidence,
        readiness_status=preview.readiness_status, issues=preview.readiness_issues,
        not_evaluated=NOT_EVALUATED)
    proof = rf.Rf1086SourceReadinessProofV2(**content,
        proof_sha256=rf.rf1086_year_source_digest(content))
    if not matches_shape(proof, rf.Rf1086SourceReadinessProofV2):
        raise rf.Rf1086YearSourceError('rf1086_source_readiness_mismatch')
    return proof


def assert_matches(proof, source, preview):
    expected = build(source, preview)
    try:
        if (not matches_shape(proof, rf.Rf1086SourceReadinessProofV2)
                or rf.rf1086_year_source_digest(proof) != rf.rf1086_year_source_digest(expected)):
            raise ValueError()
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        raise rf.Rf1086YearSourceError('rf1086_source_readiness_mismatch') from None
