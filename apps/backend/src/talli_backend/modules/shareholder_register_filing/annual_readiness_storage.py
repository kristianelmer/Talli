"""Closed canonical annual-proof bytes for immutable approval and archive binding."""
import json
from collections.abc import Mapping
from hashlib import sha256

from . import public as rf
from .year_source_storage import _encode, _decode, _unique
from .year_source import _sha


def inspect_binding(value):
    """Check retained envelope bytes; source-aware parsing still replays policy."""
    try:
        if (not isinstance(value, Mapping) or set(value) != {
                'schemaVersion', 'proofSha256', 'proofTextSha256', 'proofText'}
                or value['schemaVersion'] != 'rf1086-annual-readiness-binding-v1'
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
        if not isinstance(proof, rf.Rf1086AnnualReadinessProof):
            raise ValueError()
        rf.assert_rf1086_annual_readiness_matches(proof, source, preview, proof.annual_inputs)
        return json.dumps({'codec': 'rf1086-annual-readiness-v1', 'proof': _encode(proof)},
                          sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, AttributeError, RecursionError, ArithmeticError, rf.Rf1086YearSourceError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None


def parse(value, source, preview):
    try:
        if type(value) is not str:
            raise ValueError()
        raw = json.loads(value, object_pairs_hook=_unique)
        if (type(raw) is not dict or set(raw) != {'codec', 'proof'}
                or raw['codec'] != 'rf1086-annual-readiness-v1'):
            raise ValueError()
        proof = _decode(raw['proof'])
        if serialize(proof, source, preview) != value:
            raise ValueError()
        return proof
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, ArithmeticError, rf.Rf1086YearSourceError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None
