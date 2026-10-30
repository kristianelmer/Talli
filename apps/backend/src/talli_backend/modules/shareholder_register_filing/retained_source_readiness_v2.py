"""Retained v2 observations; callers separately establish current admission."""
from datetime import datetime
import json

from . import public as rf
from .annual_readiness import _assess
from .readiness_shape_v2 import matches_shape
from .retained_readiness import assert_preview
from .source_readiness_v2 import _compose
from .year_source import _uuid
from .annual_readiness_storage_v2 import _encode


def build_source(source, retained_preview):
    """Bind the saved payload/profile without asking today's renderer to run."""
    try:
        if (type(source) is not rf.Rf1086YearSourceSnapshotV2
                or type(retained_preview) is not rf.Rf1086ArchiveSourcePreview
                or type(retained_preview.created_by) is not str
                or type(retained_preview.created_at) is not str):
            raise ValueError()
        _uuid(retained_preview.created_by)
        created_at = datetime.fromisoformat(retained_preview.created_at)
        if created_at.tzinfo is None:
            raise ValueError()
        assert_preview(source, retained_preview.preview,
            preview_payload_sha256=retained_preview.payload_sha256,
            preview_payload_text=retained_preview.payload_text)
        if created_at < source.confirmed_at:
            raise ValueError()
        return _compose(source, retained_preview.preview)
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError, RecursionError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None


def build_annual(source, retained_preview, inputs):
    """Apply the unchanged annual policy to current inputs and saved rendering."""
    try:
        source_proof = build_source(source, retained_preview)
        content = dict(schema_version='rf1086-annual-readiness-v2', source=source_proof,
            **_assess(source_proof, inputs, source))
        result = rf.Rf1086AnnualReadinessProofV2(**content,
            proof_sha256=rf.rf1086_year_source_digest(content))
        if not matches_shape(result, rf.Rf1086AnnualReadinessProofV2):
            raise ValueError()
        return result
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError, RecursionError):
        raise rf.Rf1086YearSourceError('rf1086_annual_inputs_unavailable') from None


def serialize_annual(proof, source, retained_preview):
    """Exact v2 codec for retained blocked/warning/ready policy, without rendering."""
    try:
        if type(proof) is not rf.Rf1086AnnualReadinessProofV2:
            raise ValueError()
        if proof != build_annual(source, retained_preview, proof.annual_inputs):
            raise ValueError()
        return json.dumps({'codec': 'rf1086-annual-readiness-v2', 'proof': _encode(proof)},
            sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError, RecursionError,
            rf.Rf1086YearSourceError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None
