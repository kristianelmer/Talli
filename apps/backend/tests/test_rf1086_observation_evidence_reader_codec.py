"""Frozen emitter compatibility vectors shared with the isolated SQL parity probe.

These pure tests protect historical Python bytes/hashes, not SQL authorization.
The evidence reader additionally rejects non-emitter encodings and wrong typed
wrappers even where the older generic parser accepted an equivalent value.
"""
from dataclasses import replace
from datetime import timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import IncomeYear

GOLDENS = json.loads((Path(__file__).parent / 'fixtures/rf1086_observation_evidence_reader_v1.json').read_text())['goldens']


@pytest.mark.parametrize('golden', GOLDENS, ids=lambda item: item['name'])
def test_unchanged_v1_emitter_and_both_digests(golden):
    value = rf.parse_rf1086_register_observation(golden['snapshot_text'])
    assert rf.serialize_rf1086_register_observation(value) == golden['snapshot_text']
    assert value.fact_sha256 == golden['fact_sha256']
    assert rf.rf1086_register_observation_request_digest(value.command) == golden['request_sha256']


def parity_vectors():
    """Legitimate emitted forms, including Decimal/time/Unicode edge cases."""
    vectors = [(g['name'], rf.parse_rf1086_register_observation(g['snapshot_text'])) for g in GOLDENS]
    base = vectors[0][1]
    def prepare(name, command, at=None):
        context = rf.Rf1086VerifiedRegisterObservationContext(command.actor_id, True, command.company_id,
            command.income_year, command.documents, True)
        value = rf.prepare_rf1086_register_observation(command, context=context,
            observation_id=base.observation_id, confirmed_at=at or base.confirmed_at)
        vectors.append((name, value))
    for scale in range(7):
        quantum = Decimal(1).scaleb(-scale)
        command = replace(base.command,
            before=replace(base.command.before, share_capital=Decimal(60000).quantize(quantum), nominal_value=Decimal(600).quantize(quantum)),
            after=replace(base.command.after, share_capital=Decimal(120000).quantize(quantum), nominal_value=Decimal(600).quantize(quantum)))
        prepare('trailing_scale_' + str(scale), command)
    for index, offset in enumerate((timedelta(0), timedelta(hours=5, minutes=30), timedelta(hours=-4),
                                  timedelta(seconds=30), timedelta(seconds=-30, microseconds=-123456))):
        command = replace(base.command, documents=tuple(replace(d, created_at=d.created_at.astimezone(timezone(offset))) for d in base.command.documents))
        prepare('document_offset_' + str(index), command)
        vectors.append(('capture_offset_' + str(index), replace(base, confirmed_at=base.confirmed_at.astimezone(timezone(offset)))))
    prepare('source_year_different', replace(base.command, documents=tuple(replace(d, source_income_year=IncomeYear(2024)) for d in base.command.documents)))
    prepare('capture_microseconds', base.command, base.confirmed_at.replace(microsecond=321000))
    # A single document may supply several roles; equivalent instants with
    # different offset encodings remain consistent in the old Python model.
    first = base.command.documents[0]
    prepare('same_document_multiple_roles', replace(base.command, documents=tuple(
        replace(first, role=role, created_at=first.created_at.astimezone(timezone(timedelta(hours=index))))
        for index, role in enumerate(('register_after', 'register_before', 'registration')))))
    for index, identifier in enumerate(('ø 😀 a\u030a', '\ue000', '\U00010000', '\uffff', '\u2028\u2029\n\t')):
        def state(value):
            return replace(value, holdings=tuple(replace(h, shareholder_id='holder ' + identifier, name='Unicode ' + identifier) for h in value.holdings))
        prepare('unicode_' + str(index), replace(base.command, before=state(base.command.before), after=state(base.command.after)))
    # The final vector reaches Python 3.12's unchanged 4,300-digit bare-integer
    # conversion ceiling. Its Decimal capital strings are longer and stay valid.
    for name, count, nominal in (('fractional_nominal', 1000, Decimal('123.456789')),
                                 ('large_integer', 2**60, Decimal('600')),
                                 ('integer_4300_digits', 10**4299, Decimal('600'))):
        def state(multiplier):
            n = count * multiplier
            return rf.Rf1086RegisteredShareState(nominal * n, n, nominal,
                (replace(base.command.before.holdings[0], share_count=n),))
        prepare('exact_arithmetic_' + name, replace(base.command, before=state(1), after=state(2)))
    return vectors


@pytest.mark.parametrize('name,value', parity_vectors(), ids=lambda item: item if isinstance(item, str) else '')
def test_additional_emitter_vectors_round_trip(name, value):
    encoded = rf.serialize_rf1086_register_observation(value)
    restored = rf.parse_rf1086_register_observation(encoded)
    assert restored == value
    assert rf.serialize_rf1086_register_observation(restored) == encoded
