"""Saved RF commitments and versioned annual assessment, without rendering.

This proves internal consistency of retained evidence, not its authentic origin,
currentness, complete enumeration, permission or original document bytes. A
legacy lineage without payload_text commits only the canonical saved preview.
The existing public fresh builders/codecs deliberately keep their own behavior.
"""
import json

from . import annual_readiness_storage as storage_v1
from . import annual_readiness_storage_v2 as storage_v2
from . import public as rf
from .annual_readiness import _assess
from .readiness_shape_v2 import matches_shape
from .source_approval_encoding import _hash, _require
from .source_preview import _assert_integrity
from .source_readiness import _compose as source_proof_v1
from .source_readiness_v2 import _compose as source_proof_v2
from .year_source import _sha, _uuid


def assert_preview(source, preview, *, preview_payload_sha256,
                   preview_payload_text=None):
    """Bind saved bytes/assessment to exact source identity; never regenerate XML."""
    try:
        if type(source) is rf.Rf1086YearSourceSnapshot:
            rf.assert_rf1086_year_source_integrity(source)
        elif type(source) is rf.Rf1086YearSourceSnapshotV2:
            rf.assert_rf1086_year_source_integrity_v2(source)
        else:
            raise ValueError()
        _require(matches_shape(preview, rf.Rf1086SourcePreview))
        _assert_integrity(preview)
        _uuid(preview.preview_id.value)
        _sha(preview_payload_sha256)
        _require(preview.company_id == source.company_id
                 and preview.income_year == source.income_year
                 and preview.source_id == source.source_id
                 and preview.source_sha256 == source.source_sha256
                 and preview.case_sha256 == source.case_sha256)
        canonical = rf.serialize_rf1086_source_preview(preview)
        _require(_hash(canonical) == preview_payload_sha256)
        if preview_payload_text is not None:
            _require(type(preview_payload_text) is str
                     and _hash(preview_payload_text) == preview_payload_sha256)
            parsed = rf.parse_rf1086_source_preview(preview_payload_text)
            _require(matches_shape(parsed, rf.Rf1086SourcePreview) and parsed == preview)
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError,
            RecursionError, rf.ShareholderRegisterFilingError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None


def _annual(proof, source, preview):
    """Rebuild saved source commitments and the v1/v2 annual policy, not renderer output."""
    if type(source) is rf.Rf1086YearSourceSnapshot:
        kind, compose, schema, storage = (rf.Rf1086AnnualReadinessProof, source_proof_v1,
            'rf1086-annual-readiness-v1', storage_v1)
    elif type(source) is rf.Rf1086YearSourceSnapshotV2:
        kind, compose, schema, storage = (rf.Rf1086AnnualReadinessProofV2, source_proof_v2,
            'rf1086-annual-readiness-v2', storage_v2)
    else:
        raise ValueError()
    _require(matches_shape(proof, kind))
    source_proof = compose(source, preview)
    # _assess is the existing policy shared by exactly annual v1 and v2. Future
    # policy versions must retain this assessment for these historical codecs.
    content = dict(schema_version=schema, source=source_proof,
                   **_assess(source_proof, proof.annual_inputs, source))
    expected = kind(**content, proof_sha256=rf.rf1086_year_source_digest(content))
    _require(matches_shape(expected, kind) and proof == expected)
    return storage, schema


def annual_binding(proof, source, preview, *, preview_payload_sha256,
                   preview_payload_text=None):
    """Validate a typed retained annual proof and reproduce its exact closed binding."""
    try:
        assert_preview(source, preview, preview_payload_sha256=preview_payload_sha256,
                       preview_payload_text=preview_payload_text)
        storage, schema = _annual(proof, source, preview)
        _require(proof.readiness_status in ('ready', 'warning'))
        text = json.dumps({'codec': schema, 'proof': storage._encode(proof)},
                          sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        binding_schema = ('rf1086-annual-readiness-binding-v1' if storage is storage_v1
                          else 'rf1086-annual-readiness-binding-v2')
        return {'schemaVersion': binding_schema, 'proofSha256': proof.proof_sha256,
                'proofTextSha256': _hash(text), 'proofText': text}
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError,
            RecursionError, rf.ShareholderRegisterFilingError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None


def parse_annual_binding(value, source, preview, *, preview_payload_sha256,
                         preview_payload_text=None):
    """Parse exact retained bytes with the matching codec and replay their annual assessment."""
    try:
        if type(source) is rf.Rf1086YearSourceSnapshot:
            storage, schema = storage_v1, 'rf1086-annual-readiness-v1'
        elif type(source) is rf.Rf1086YearSourceSnapshotV2:
            storage, schema = storage_v2, 'rf1086-annual-readiness-v2'
        else:
            raise ValueError()
        text = storage.inspect_binding(value)
        raw = json.loads(text, object_pairs_hook=storage._unique)
        _require(type(raw) is dict and set(raw) == {'codec', 'proof'} and raw['codec'] == schema)
        proof = storage._decode(raw['proof'])
        expected = annual_binding(proof, source, preview,
            preview_payload_sha256=preview_payload_sha256, preview_payload_text=preview_payload_text)
        _require(expected == value)
        return proof
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError,
            RecursionError, rf.ShareholderRegisterFilingError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None
