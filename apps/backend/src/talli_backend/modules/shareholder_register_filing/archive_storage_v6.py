"""Explicit retained archive reading and complete v6 serialization.

Legacy envelopes keep their original bytes and unknown coverage. V6 captures all
three sections, but internal consistency cannot prove authoritative completeness,
authentic origin, retained document bytes, or current admission to file.
"""
from hashlib import sha256
import json

from talli_backend.shared.kernel import IncomeYear
from . import archive_storage as legacy
from . import public as rf
from .archive_codec import decode, encode
from .preparation import _validate_retained_archive_source
from .year_source_storage import _unique

_CODEC = 'rf1086-production-archive-v6'
_RECORDS = {**legacy._RECORDS, **{kind.__name__: kind for kind in (
    rf.Rf1086YearGovernanceChainV2, rf.Rf1086YearGovernanceHeadV2,
    rf.Rf1086YearGovernanceLinkV2, rf.Rf1086YearGovernanceProjectionV2,
    rf.Rf1086YearGovernanceReceiptV2, rf.Rf1086YearRegisterFactV2,
    rf.Rf1086YearSourceFreshnessV2, rf.Rf1086YearSourceSnapshotV2,
)}}
_CODECS = (_CODEC, legacy._CODEC, legacy._OVERRIDE_CODEC, legacy._FEEDBACK_CODEC,
           legacy._HISTORY_CODEC, legacy._LEGACY_CODEC)


def _encode(value):
    return encode(value, records=_RECORDS, enums=legacy._ENUMS)


def _validate(query, snapshot):
    if not isinstance(query, rf.Rf1086ArchiveQuery) or not isinstance(snapshot, rf.Rf1086ArchiveSnapshot):
        raise ValueError()
    if not isinstance(snapshot.income_year, IncomeYear) or type(snapshot.income_year.value) is not int:
        raise ValueError()
    return _validate_retained_archive_source(query, snapshot)


def serialize(snapshot, *, query):
    """Emit canonical v6 only when history, overrides and withdrawals are captured."""
    try:
        _validate(query, snapshot)
        if (type(snapshot.source_history) is not rf.Rf1086ArchiveSourceHistory
                or type(snapshot.overrides) is not tuple
                or type(snapshot.withdrawal_capture_records) is not tuple):
            raise ValueError()
        text = legacy._text(_encode(snapshot))
        result = legacy._text({'codec': _CODEC, 'snapshotText': text,
                               'sha256': sha256(text.encode('utf-8')).hexdigest()})
        if len(result.encode('utf-8')) > legacy._MAX_BYTES:
            raise ValueError()
        return result
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError, RecursionError,
            rf.ShareholderRegisterFilingError):
        raise rf.Rf1086ArchiveError('rf1086_archive_storage_invalid') from None


def parse(value, *, query):
    """Read v1–v6 under explicit retained semantics; never fall back to fresh validation."""
    try:
        if type(value) is not str or len(value.encode('utf-8')) > legacy._MAX_BYTES:
            raise ValueError()
        envelope = json.loads(value, object_pairs_hook=_unique)
        if (type(envelope) is not dict or set(envelope) != {'codec', 'snapshotText', 'sha256'}
                or envelope['codec'] not in _CODECS or type(envelope['snapshotText']) is not str
                or sha256(envelope['snapshotText'].encode('utf-8')).hexdigest() != envelope['sha256']):
            raise ValueError()
        codec = envelope['codec']
        encoded = json.loads(envelope['snapshotText'], object_pairs_hook=_unique)
        if (type(encoded) is not dict or encoded.get('record') != 'Rf1086ArchiveSnapshot'
                or type(encoded.get('fields')) is not dict):
            raise ValueError()
        if codec == legacy._LEGACY_CODEC:
            if 'source_history' in encoded['fields']:
                raise ValueError()
            encoded['fields']['source_history'] = None
        elif encoded['fields'].get('source_history') is None:
            raise ValueError()
        if codec in (_CODEC, legacy._CODEC, legacy._OVERRIDE_CODEC):
            if type(encoded['fields'].get('overrides')) is not list:
                raise ValueError()
        else:
            if 'overrides' in encoded['fields']:
                raise ValueError()
            encoded['fields']['overrides'] = None
        if codec in (_CODEC, legacy._CODEC):
            if type(encoded['fields'].get('withdrawal_capture_records')) is not list:
                raise ValueError()
        else:
            if 'withdrawal_capture_records' in encoded['fields']:
                raise ValueError()
            encoded['fields']['withdrawal_capture_records'] = None
        # A legacy label never acquires the v2 record allowlist.
        snapshot = decode(encoded, records=_RECORDS if codec == _CODEC else legacy._RECORDS,
            enums=legacy._ENUMS, legacy=codec in (legacy._LEGACY_CODEC, legacy._HISTORY_CODEC))
        if codec == legacy._FEEDBACK_CODEC and not any(row.original_id is not None for row in snapshot.feedback_artifacts):
            raise ValueError()
        if codec == _CODEC and (legacy._text(envelope) != value
                or legacy._text(_encode(snapshot)) != envelope['snapshotText']):
            raise ValueError()
        return _validate(query, snapshot)
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError, RecursionError,
            rf.ShareholderRegisterFilingError):
        raise rf.Rf1086ArchiveError('rf1086_archive_storage_invalid') from None
