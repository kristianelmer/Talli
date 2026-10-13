"""Exact, private catalog predictions for the two fixed diagnostic branches.

Source rows replace only their declared scalar spans. Every other byte of the
failed capture remains part of the prediction; no recovery rule uses this API.
"""
from dataclasses import dataclass, field
import hashlib
import json
import math
import struct
import time

from rf1086_catalog_causal_capture import NET_IDENTITIES, SCHEMAS
from rf1086_catalog_difference import (
    CatalogCapture, MAX_CAPTURE_BYTES, MAX_RECORDS, _object, _records,
    _reject_constant,
)

_DECODER = json.JSONDecoder(object_pairs_hook=_object, parse_constant=_reject_constant)
_CHUNK = 65536
_SPACE = ' \t\r\n'


class PredictionUnavailable(ValueError):
    def __init__(self, reason='raw_prediction'):
        self.reason = reason
        super().__init__('causal_catalog_unavailable')


def _alive(deadline):
    if (type(deadline) not in (int, float) or not math.isfinite(deadline)
            or time.monotonic() >= deadline):
        raise PredictionUnavailable('deadline')


def _items(text, deadline):
    """Yield decoded top-level items and exact character spans in a JSON array."""
    position = 0

    def space(at):
        while at < len(text) and text[at] in _SPACE:
            at += 1
        return at

    position = space(position)
    if position == len(text) or text[position] != '[':
        raise PredictionUnavailable()
    position = space(position + 1)
    count = 0
    if position < len(text) and text[position] == ']':
        position = space(position + 1)
    else:
        while True:
            _alive(deadline)
            start = position
            value, position = _DECODER.raw_decode(text, position)
            count += 1
            if count > MAX_RECORDS:
                raise PredictionUnavailable()
            yield value, start, position
            position = space(position)
            if position >= len(text):
                raise PredictionUnavailable()
            delimiter = text[position]
            position = space(position + 1)
            if delimiter == ']':
                break
            if delimiter != ',' or position >= len(text) or text[position] == ']':
                raise PredictionUnavailable()
    if position != len(text):
        raise PredictionUnavailable()


def _selected(raw, identities, catalog, group, deadline):
    _alive(deadline)
    with CatalogCapture() as capture:
        capture.capture(raw)
        _records(capture)  # Existing typed, duplicate/depth/count/size validation.
    _alive(deadline)
    rows = catalog[group]
    if type(rows) is not list:
        raise PredictionUnavailable()
    expected = {}
    for identity in identities:
        matches = [item for item in rows if item.get('identity') == list(identity)]
        if len(matches) != 1:
            raise PredictionUnavailable()
        expected[identity] = matches[0]['row']
    text = raw.split(b'\n', 1)[0].decode('utf-8')
    selected = {}
    last_character = last_byte = 0
    for row, start, end in _items(text, deadline):
        start_byte = last_byte + len(text[last_character:start].encode('utf-8'))
        end_byte = start_byte + len(text[start:end].encode('utf-8'))
        last_character, last_byte = end, end_byte
        if type(row) is not list:
            raise PredictionUnavailable()
        identity = tuple(row[:len(identities[0])])
        if identity in expected:
            if identity in selected or row != expected[identity]:
                raise PredictionUnavailable()
            selected[identity] = (start_byte, end_byte, row)
    if set(selected) != set(expected):
        raise PredictionUnavailable()
    return selected


def _admit_row(source, failed, source_row, failed_row, fields, deadline):
    if (len(source_row) != len(failed_row)
            or [i for i, pair in enumerate(zip(source_row, failed_row, strict=True))
                if pair[0] != pair[1]] != list(fields)):
        raise PredictionUnavailable()
    source_text, failed_text = source.decode('utf-8'), failed.decode('utf-8')
    source_slots = list(_items(source_text, deadline))
    failed_slots = list(_items(failed_text, deadline))
    if (len(source_slots) != len(source_row) or len(failed_slots) != len(failed_row)
            or [slot[0] for slot in source_slots] != source_row
            or [slot[0] for slot in failed_slots] != failed_row):
        raise PredictionUnavailable()
    pieces, at = [], 0
    for index in fields:
        _, begin, end = failed_slots[index]
        _, source_begin, source_end = source_slots[index]
        pieces.extend((failed_text[at:begin], source_text[source_begin:source_end]))
        at = end
    pieces.append(failed_text[at:])
    # Equality also checks spelling and whitespace of every undeclared field.
    if ''.join(pieces).encode('utf-8') != source:
        raise PredictionUnavailable()


@dataclass(frozen=True)
class Prediction:
    kind: str
    _failed: bytes = field(repr=False)
    _replacements: tuple = field(repr=False)
    _expected_bytes: int
    _expected_sha256: str
    _outside_sha256: str

    @property
    def binding(self):
        return {'expected': {'bytes': self._expected_bytes,
                             'sha256': self._expected_sha256},
                'outside': self._outside_sha256}

    def _segments(self):
        at = 0
        for begin, end, replacement in self._replacements:
            yield memoryview(self._failed)[at:begin]
            yield memoryview(replacement)
            at = end
        yield memoryview(self._failed)[at:]

    def compare(self, actual_raw, deadline):
        """Compare the complete conceptual prediction without reserialization."""
        _alive(deadline)
        if type(actual_raw) is not bytes or len(actual_raw) != self._expected_bytes:
            raise PredictionUnavailable('raw_prediction_mismatch')
        actual, position, hashed = memoryview(actual_raw), 0, hashlib.sha256()
        for segment in self._segments():
            for offset in range(0, len(segment), _CHUNK):
                _alive(deadline)
                expected = segment[offset:offset + _CHUNK]
                observed = actual[position:position + len(expected)]
                if observed != expected:
                    raise PredictionUnavailable('raw_prediction_mismatch')
                hashed.update(observed)
                position += len(observed)
        _alive(deadline)
        if position != len(actual) or hashed.hexdigest() != self._expected_sha256:
            raise PredictionUnavailable('raw_prediction_mismatch')
        return self.binding | {'actual': {'bytes': position, 'sha256': hashed.hexdigest()}}


def prepare_prediction(kind, source_raw, failed_raw, *, source_catalog,
                       failed_catalog, deadline):
    """Freeze two source-row substitutions before any intervention is delivered."""
    try:
        _alive(deadline)
        if kind == 'Is':
            identities, group, fields = tuple(map(tuple, SCHEMAS)), 'schemas', (3,)
        elif kind == 'In':
            identities, group, fields = tuple(map(tuple, NET_IDENTITIES)), 'functions', (6, 7)
        else:
            raise PredictionUnavailable()
        if any(type(raw) is not bytes or not 0 < len(raw) <= MAX_CAPTURE_BYTES
               for raw in (source_raw, failed_raw)):
            raise PredictionUnavailable()
        source = _selected(source_raw, identities, source_catalog, group, deadline)
        failed = _selected(failed_raw, identities, failed_catalog, group, deadline)
        replacements = []
        for identity in identities:
            sb, se, source_row = source[identity]
            fb, fe, failed_row = failed[identity]
            source_span, failed_span = source_raw[sb:se], failed_raw[fb:fe]
            _admit_row(source_span, failed_span, source_row, failed_row, fields, deadline)
            replacements.append((fb, fe, source_span))
        replacements.sort()
        size = len(failed_raw) + sum(len(value) - (end-begin)
                                    for begin, end, value in replacements)
        if not 0 < size <= MAX_CAPTURE_BYTES:
            raise PredictionUnavailable()
        outside = hashlib.sha256(b'causal-outside-v1\0')
        expected = hashlib.sha256()
        at = 0
        for begin, end, replacement in (*replacements, (len(failed_raw), len(failed_raw), b'')):
            gap = memoryview(failed_raw)[at:begin]
            outside.update(struct.pack('>Q', len(gap)))
            for offset in range(0, len(gap), _CHUNK):
                _alive(deadline)
                chunk = gap[offset:offset+_CHUNK]
                outside.update(chunk)
                expected.update(chunk)
            expected.update(replacement)
            at = end
        _alive(deadline)
        return Prediction(kind, failed_raw, tuple(replacements), size,
                          expected.hexdigest(), outside.hexdigest())
    except PredictionUnavailable:
        raise
    except Exception:
        raise PredictionUnavailable() from None
