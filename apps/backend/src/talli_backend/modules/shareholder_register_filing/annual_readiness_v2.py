"""V2 evidence assessed by the same RF annual policy as frozen v1."""
from . import public as rf
from .annual_readiness import _assess
from .readiness_shape_v2 import matches_shape


def build(source, preview, inputs):
    try:
        source_proof = rf.build_rf1086_source_readiness_v2(source, preview)
        content = dict(schema_version='rf1086-annual-readiness-v2', source=source_proof,
                       **_assess(source_proof, inputs, source))
        proof = rf.Rf1086AnnualReadinessProofV2(**content,
            proof_sha256=rf.rf1086_year_source_digest(content))
        if not matches_shape(proof, rf.Rf1086AnnualReadinessProofV2):
            raise ValueError()
        return proof
    except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError):
        raise rf.Rf1086YearSourceError('rf1086_annual_inputs_unavailable') from None


def assert_matches(proof, source, preview, inputs):
    expected = build(source, preview, inputs)
    if (not matches_shape(proof, rf.Rf1086AnnualReadinessProofV2)
            or rf.rf1086_year_source_digest(proof) != rf.rf1086_year_source_digest(expected)):
        raise rf.Rf1086YearSourceError('rf1086_annual_readiness_mismatch')
