"""Independent closed v2 annual-proof codec; no source or archive registry reuse."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from hashlib import sha256
import json

from talli_backend.shared.kernel import CompanyId, IncomeYear
from . import public as rf
from .year_source import _sha


_RECORDS = {kind.__name__: kind for kind in (
    CompanyId, IncomeYear, rf.Rf1086YearSourceId, rf.PreviewId,
    rf.Rf1086YearSourceFreshnessV2, rf.Rf1086SourceReadinessEvidenceV2,
    rf.Rf1086SourceReadinessProofV2, rf.Rf1086ReadinessIssue,
    rf.Rf1086AnnualDocumentStatus, rf.Rf1086AnnualReadinessInputs,
    rf.Rf1086AnnualReadinessProofV2,
)}


def _encode(value):
    if value is None or type(value) in (bool, str, int):
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError()
        return {'mapping': {key: _encode(item) for key, item in value.items()}}
    if type(value) is tuple:
        return [_encode(item) for item in value]
    if is_dataclass(value) and _RECORDS.get(type(value).__name__) is type(value):
        return {'record': type(value).__name__, 'fields': {
            field.name: _encode(getattr(value, field.name)) for field in fields(value)}}
    raise ValueError()


def _decode(value):
    if value is None or type(value) in (bool, str, int):
        return value
    if type(value) is list:
        return tuple(_decode(item) for item in value)
    if type(value) is not dict:
        raise ValueError()
    if set(value) == {'mapping'} and type(value['mapping']) is dict:
        return {key: _decode(item) for key, item in value['mapping'].items()}
    if set(value) == {'record', 'fields'} and value['record'] in _RECORDS:
        kind = _RECORDS[value['record']]
        if type(value['fields']) is not dict or set(value['fields']) != {field.name for field in fields(kind)}:
            raise ValueError()
        return kind(**{name: _decode(item) for name, item in value['fields'].items()})
    raise ValueError()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def inspect_binding(value):
    """Verify a v2 envelope; source-aware parsing separately replays the policy."""
    try:
        if (not isinstance(value, Mapping) or set(value) != {
                'schemaVersion', 'proofSha256', 'proofTextSha256', 'proofText'}
                or value['schemaVersion'] != 'rf1086-annual-readiness-binding-v2'
                or type(value['proofText']) is not str):
            raise ValueError()
        _sha(value['proofSha256'])
        _sha(value['proofTextSha256'])
        if sha256(value['proofText'].encode('utf-8')).hexdigest() != value['proofTextSha256']:
            raise ValueError()
        return value['proofText']
    except (ValueError, TypeError, KeyError, rf.Rf1086YearSourceError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None


def parse_binding(value, source, preview):
    proof = parse(inspect_binding(value), source, preview)
    if proof.proof_sha256 != value['proofSha256'] or proof.readiness_status not in ('ready', 'warning'):
        raise rf.Rf1086ProductionError('basis_unavailable')
    return proof


def serialize(proof, source, preview):
    try:
        if type(proof) is not rf.Rf1086AnnualReadinessProofV2:
            raise ValueError()
        rf.assert_rf1086_annual_readiness_matches_v2(proof, source, preview, proof.annual_inputs)
        return json.dumps({'codec': 'rf1086-annual-readiness-v2', 'proof': _encode(proof)},
                          sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, AttributeError, RecursionError, ArithmeticError, rf.Rf1086YearSourceError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None


def parse(value, source, preview):
    try:
        if type(value) is not str:
            raise ValueError()
        raw = json.loads(value, object_pairs_hook=_unique)
        if (type(raw) is not dict or set(raw) != {'codec', 'proof'}
                or raw['codec'] != 'rf1086-annual-readiness-v2'):
            raise ValueError()
        proof = _decode(raw['proof'])
        if serialize(proof, source, preview) != value:
            raise ValueError()
        return proof
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, ArithmeticError,
            rf.Rf1086YearSourceError, rf.ShareholderRegisterFilingError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None
