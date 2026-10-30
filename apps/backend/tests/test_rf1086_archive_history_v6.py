"""Retained mixed history consistency, not origin authenticity or current admission.

Real pure RF constructors mint observation/withdrawal receipts. Governance origin
commitments remain synthetic fixture labels; no SQL, owner, or byte-store proof.
"""
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.modules.shareholder_register_filing.archive_history_v6 import validate
from test_rf1086_archive_history import history_archive
from test_rf1086_source_preview import preview_source
from test_rf1086_source_production import source_case, source_for
from test_rf1086_withdrawal_archive import withdrawal_archive
from test_rf1086_year_source_v2 import (
    CONFIRMED, NOW, identity, observation, prepare, projection, register_fact, v2_basis,
)


def capture_source(source):
    serialize = (rf.serialize_rf1086_year_source_v2 if type(source) is rf.Rf1086YearSourceSnapshotV2
                 else rf.serialize_rf1086_year_source)
    return rf.Rf1086ArchiveCaptureRecord(source.source_id.value, 'source:' + source.source_id.value,
        rf.rf1086_year_source_digest(source.command), serialize(source))


def capture_observation(row):
    return rf.Rf1086ArchiveCaptureRecord(row.observation_id.value, 'observation:' + row.observation_id.value,
        rf.rf1086_register_observation_request_digest(row.command), rf.serialize_rf1086_register_observation(row))


def capture_withdrawal(row):
    return rf.Rf1086ArchiveCaptureRecord(row.withdrawal_id.value, 'withdrawal:' + row.withdrawal_id.value,
        row.request_sha256, rf.serialize_rf1086_register_observation_withdrawal(row))


def withdraw(target, number, instant):
    command = rf.WithdrawRf1086RegisterObservation(target.command.company_id, target.command.actor_id,
        target.command.income_year, target.observation_id, target.version, target.fact_sha256,
        'Retain the replaced observation.\nÆrlig historikk.')
    return rf.prepare_rf1086_register_observation_withdrawal(command, observation=target,
        withdrawal_id=rf.Rf1086RegisterObservationWithdrawalId(identity(number)), withdrawn_at=instant)


def mixed_archive(kind='cash_issue', amendments=2, *, legacy=False, previews=False):
    command, context = v2_basis(kind, amendments=amendments)
    observations, withdrawals, chains = [], [], []
    for chain in context.governance_projection.chains:
        event_index = next(row.event_index for row in command.event_evidence
                           if row.governance_receipt_id == chain.receipt_id)
        first = observation(command, event_index, 1000 + event_index * 100, NOW - timedelta(days=3))
        observations.append(first)
        target, links = first, []
        for revision, link in enumerate(chain.amendments, 1):
            replacement = observation(command, event_index, 1000 + event_index * 100 + revision,
                                      NOW + timedelta(hours=revision))
            receipt = withdraw(target, 3000 + event_index * 100 + revision,
                               link.recorded_at - timedelta(seconds=1))
            links.append(replace(link, withdrawal_sha256=receipt.withdrawal_sha256))
            observations.append(replacement)
            withdrawals.append(receipt)
            target = replacement
        chains.append(replace(chain, amendments=tuple(links)))
    context = replace(context, governance_projection=projection(tuple(chains),
        original_sha=context.governance_projection.original_enumeration_sha256))
    previous = source_for(source_case('no_activity')) if legacy else None
    if previous:
        command = replace(command, supersedes_source_id=previous.source_id,
            supersedes_source_sha256=previous.source_sha256, correction_reason='Explicit v1 to v2 correction')
    source = prepare(command, context, source_id=rf.Rf1086YearSourceId(identity(6600)), previous=previous)
    sources = (previous, source) if previous else (source,)
    records = ()
    if previews:
        preview = preview_source(source)[0]
        text = rf.serialize_rf1086_source_preview(preview)
        records = (rf.Rf1086ArchiveSourcePreview(preview, text, sha256(text.encode()).hexdigest(),
            source.confirmed_by.subject.value, (CONFIRMED + timedelta(seconds=1)).isoformat()),)
    history = rf.Rf1086ArchiveSourceHistory(sources,
        rf.Rf1086ArchiveYearSourceHead(source.company_id, source.income_year, source.source_id,
                                      source.version, source.source_sha256),
        tuple(observations), records, (), tuple(map(capture_source, sources)),
        tuple(map(capture_observation, observations)))
    return rf.Rf1086ArchiveSnapshot(source.company_id, source.income_year, source_history=history,
        overrides=(), withdrawal_capture_records=tuple(map(capture_withdrawal, withdrawals))), context


def with_sources(archive, sources):
    head = None if not sources else rf.Rf1086ArchiveYearSourceHead(sources[-1].company_id,
        sources[-1].income_year, sources[-1].source_id, sources[-1].version, sources[-1].source_sha256)
    return replace(archive, source_history=replace(archive.source_history, year_sources=sources,
        year_source_head=head, source_capture_records=tuple(map(capture_source, sources))))


def replace_projection(archive, context, chains):
    context = replace(context, governance_projection=projection(chains,
        original_sha=context.governance_projection.original_enumeration_sha256))
    old = archive.source_history.year_sources[-1]
    previous = archive.source_history.year_sources[-2] if len(archive.source_history.year_sources) > 1 else None
    source = prepare(old.command, context, source_id=old.source_id, previous=previous)
    return with_sources(archive, (*archive.source_history.year_sources[:-1], source))


@pytest.mark.parametrize('kind', ['no_activity', 'formation', 'dividend', 'cash_issue', 'loss_covering_reduction', 'mixed'])
@pytest.mark.parametrize('amendments', [0, 1, 2])
def test_actual_observation_roots_and_withdrawals_survive_mixed_history(kind, amendments):
    archive, _ = mixed_archive(kind, amendments, legacy=True, previews=True)
    before = archive.source_history.source_capture_records
    validate(archive)
    assert archive.source_history.source_capture_records == before
    assert [row.version for row in archive.source_history.year_sources] == [1, 2]
    assert all(row.version == 1 for row in archive.source_history.register_observations)
    assert len(archive.withdrawal_capture_records) == len(archive.source_history.year_sources[-1].governance_projection.chains) * amendments


@pytest.mark.parametrize('approved', [False, True])
@pytest.mark.parametrize('withdrawals', [False, True])
def test_existing_history_uses_unchanged_saved_projection_without_renderer(monkeypatch, approved, withdrawals):
    archive = withdrawal_archive()[0] if withdrawals else history_archive(approved=approved)[0]
    def forbidden(*args, **kwargs): raise AssertionError('History must not render')
    monkeypatch.setattr(rf, 'render_rf1086_preview', forbidden)
    monkeypatch.setattr(rf, 'assert_rf1086_source_preview_matches', forbidden)
    validate(archive)


@pytest.mark.parametrize('blocked', [False, True])
def test_unapproved_raw_preview_bytes_and_noncanonical_source_capture_are_preserved(blocked):
    archive, _ = mixed_archive(previews=True)
    history = archive.source_history
    record = history.source_previews[0]
    preview = replace(record.preview, readiness_status='blocked', hovedskjema_xml=None,
                      underskjema_xml=None) if blocked else record.preview
    text = json.dumps(json.loads(rf.serialize_rf1086_source_preview(preview)), indent=2, ensure_ascii=False) + '\n'
    record = replace(record, preview=preview, payload_text=text, payload_sha256=sha256(text.encode()).hexdigest())
    capture = history.source_capture_records[0]
    raw = json.dumps(json.loads(capture.snapshot_text), indent=2, ensure_ascii=False) + '\n'
    archive = replace(archive, source_history=replace(history, source_previews=(record,),
        source_capture_records=(replace(capture, snapshot_text=raw),)))
    validate(archive)
    assert archive.source_history.source_previews[0].payload_text == text
    assert archive.source_history.source_capture_records[0].snapshot_text == raw


@pytest.mark.parametrize('coverage', [None, ()])
def test_zero_amendments_do_not_infer_unknown_withdrawal_coverage(coverage):
    archive, _ = mixed_archive(amendments=0)
    archive = replace(archive, withdrawal_capture_records=coverage)
    validate(archive)
    assert archive.withdrawal_capture_records is coverage


def test_history_none_remains_unknown_and_does_not_create_rows():
    archive = rf.Rf1086ArchiveSnapshot(*[getattr(mixed_archive()[0], key) for key in ('company_id', 'income_year')])
    validate(archive)
    assert archive.source_history is None


def test_off_year_chains_preserve_full_owner_commitments_without_local_rows():
    archive, context = mixed_archive('no_activity')
    _, capital = v2_basis(amendments=2)
    off_year = replace(capital.governance_projection.chains[0], income_year=rf.IncomeYear(2024))
    archive = replace_projection(archive, context, (off_year,))
    validate(archive)
    assert archive.source_history.register_observations == ()
    assert archive.source_history.year_sources[0].governance_projection.chains == (off_year,)


@pytest.mark.parametrize('missing', ['original', 'intermediate', 'effective'])
def test_missing_referenced_local_observation_rejected_even_with_capture_bijection(missing):
    archive, _ = mixed_archive()
    history = archive.source_history
    index = {'original': 0, 'intermediate': 1, 'effective': 2}[missing]
    retained = tuple(row for i, row in enumerate(history.register_observations) if i != index)
    archive = replace(archive, source_history=replace(history, register_observations=retained,
        observation_capture_records=tuple(map(capture_observation, retained))))
    with pytest.raises(ValueError, match='^RF source history is inconsistent$'): validate(archive)


@pytest.mark.parametrize('change', ['missing', 'unknown', 'wrong_hash', 'wrong_id', 'wrong_target', 'late'])
def test_withdrawal_reference_requires_exact_retained_receipt_and_target(change):
    archive, context = mixed_archive()
    chain = context.governance_projection.chains[0]
    link = chain.amendments[0]
    records = archive.withdrawal_capture_records
    if change == 'missing': archive = replace(archive, withdrawal_capture_records=records[1:])
    elif change == 'unknown': archive = replace(archive, withdrawal_capture_records=None)
    elif change == 'wrong_hash': link = replace(link, withdrawal_sha256='f' * 64)
    elif change == 'wrong_id': link = replace(link, withdrawal_id=identity(9191))
    else:
        target = archive.source_history.register_observations[-1] if change == 'wrong_target' else archive.source_history.register_observations[0]
        time = link.recorded_at + timedelta(seconds=1) if change == 'late' else link.recorded_at
        receipt = withdraw(target, 9191, max(time, target.confirmed_at))
        archive = replace(archive, withdrawal_capture_records=(capture_withdrawal(receipt), *records[1:]))
        link = replace(link, withdrawal_id=receipt.withdrawal_id.value, withdrawal_sha256=receipt.withdrawal_sha256)
    if change not in ('missing', 'unknown'):
        archive = replace_projection(archive, context, (replace(chain, amendments=(link, *chain.amendments[1:])),))
    with pytest.raises(ValueError, match='^RF source history is inconsistent$'): validate(archive)


@pytest.mark.parametrize('which', ['original', 'intermediate'])
def test_rehashed_source_cannot_change_exact_observation_version(which):
    archive, context = mixed_archive()
    chain = context.governance_projection.chains[0]
    if which == 'original':
        fact = replace(chain.original_register_fact, version=2)
        chain = replace(chain, original_register_fact=fact,
            amendments=(replace(chain.amendments[0], target=fact), chain.amendments[1]))
    else:
        fact = replace(chain.amendments[0].replacement, version=2)
        chain = replace(chain, amendments=(replace(chain.amendments[0], replacement=fact),
                                           replace(chain.amendments[1], target=fact)))
    archive = replace_projection(archive, context, (chain,))
    with pytest.raises(ValueError, match='^RF source history is inconsistent$'): validate(archive)


@pytest.mark.parametrize('change', ['codec', 'duplicate_raw_key', 'malformed', 'request', 'key', 'missing', 'extra', 'wrong_body'])
def test_capture_exact_codec_request_and_bijection(change):
    archive, _ = mixed_archive(legacy=True)
    history = archive.source_history
    records = history.source_capture_records
    row = records[-1]
    if change == 'codec': row = replace(row, snapshot_text=row.snapshot_text.replace('rf1086-year-source-v2', 'rf1086-year-source-v1', 1))
    elif change == 'duplicate_raw_key': row = replace(row, snapshot_text='{"codec":"rf1086-year-source-v2",' + row.snapshot_text[1:])
    elif change == 'malformed': row = replace(row, snapshot_text='{}')
    elif change == 'request': row = replace(row, request_sha256='f' * 64)
    elif change == 'key': row = replace(row, idempotency_key=records[0].idempotency_key)
    elif change == 'wrong_body': row = replace(row, snapshot_text=records[0].snapshot_text)
    if change == 'missing': records = records[:1]
    elif change == 'extra': records = (*records, replace(row, record_id=identity(9191)))
    else: records = (*records[:-1], row)
    with pytest.raises(ValueError, match='^RF source history is inconsistent$'):
        validate(replace(archive, source_history=replace(history, source_capture_records=records)))


@pytest.mark.parametrize('change', ['head', 'ordinal', 'scope', 'source_hash', 'no_predecessor', 'stale_predecessor'])
def test_source_chain_bindings_fail_closed(change):
    archive, _ = mixed_archive(legacy=True)
    history = archive.source_history
    source = history.year_sources[-1]
    if change == 'head': history = replace(history, year_source_head=replace(history.year_source_head, source_sha256='f' * 64))
    else:
        if change == 'ordinal': source = replace(source, version=1)
        elif change == 'scope': source = replace(source, income_year=rf.IncomeYear(2024))
        elif change == 'source_hash': source = replace(source, source_sha256='f' * 64)
        elif change == 'no_predecessor': source = replace(source, command=replace(source.command, supersedes_source_id=None))
        else: source = replace(source, command=replace(source.command, supersedes_source_sha256='f' * 64))
        history = replace(history, year_sources=(*history.year_sources[:-1], source))
    with pytest.raises(ValueError, match='^RF source history is inconsistent$'): validate(replace(archive, source_history=history))


def test_v2_to_v1_downgrade_is_rejected_even_for_valid_individual_snapshots():
    from test_rf1086_year_source import basis as old_basis, prepare as old_prepare
    archive, _ = mixed_archive('no_activity', amendments=0)
    first = archive.source_history.year_sources[0]
    command, context = old_basis()
    command = replace(command, supersedes_source_id=first.source_id,
        supersedes_source_sha256=first.source_sha256, correction_reason='Forbidden codec downgrade')
    with pytest.raises(rf.Rf1086YearSourceError):
        old_prepare(command, context, previous=first,
            source_id=rf.Rf1086YearSourceId(identity(6601)), confirmed_at=CONFIRMED + timedelta(seconds=1))
    # Privileged stored-payload forgery: recompute the v1 commitment over a
    # forbidden v2 predecessor. No fake predecessor is passed to a constructor.
    second = old_prepare(*old_basis(), source_id=rf.Rf1086YearSourceId(identity(6601)),
                         confirmed_at=CONFIRMED + timedelta(seconds=1))
    second = replace(second, command=command, version=2)
    digest = rf.rf1086_year_source_digest({'schema': 'rf1086-year-source-v1',
        'source_id': second.source_id, 'version': second.version, 'command': second.command,
        'confirmed_at': second.confirmed_at, 'governance_receipts': second.governance_receipts,
        'company_identity_sha256': second.freshness.company_identity_sha256,
        'governance_enumeration_sha256': second.freshness.governance_enumeration_sha256})
    second = replace(second, source_sha256=digest, freshness=replace(second.freshness, source_sha256=digest))
    rf.assert_rf1086_year_source_integrity(second)
    with pytest.raises(ValueError, match='^RF source history is inconsistent$'):
        validate(with_sources(archive, (first, second)))


@pytest.mark.parametrize('change', ['hash', 'source', 'scope', 'time', 'malformed'])
def test_saved_preview_binding_is_checked_without_rerender(change):
    archive, _ = mixed_archive(previews=True)
    history = archive.source_history
    row = history.source_previews[0]
    if change == 'hash': row = replace(row, payload_sha256='f' * 64)
    elif change == 'time': row = replace(row, created_at=NOW.isoformat())
    elif change == 'malformed': row = replace(row, payload_text='{}')
    else:
        preview = replace(row.preview, **({'source_sha256': 'f' * 64} if change == 'source' else {'income_year': rf.IncomeYear(2024)}))
        text = rf.serialize_rf1086_source_preview(preview)
        row = replace(row, preview=preview, payload_text=text, payload_sha256=sha256(text.encode()).hexdigest())
    with pytest.raises(ValueError, match='^RF source history is inconsistent$'):
        validate(replace(archive, source_history=replace(history, source_previews=(row,))))


def test_legacy_validator_and_serializer_do_not_activate_v2_history():
    from talli_backend.modules.shareholder_register_filing.archive_history import validate as legacy_validate
    from test_rf1086_archive_storage import query
    archive, _ = mixed_archive()
    with pytest.raises(ValueError): legacy_validate(archive)
    with pytest.raises(rf.Rf1086ArchiveError): rf.serialize_rf1086_archive(archive, query=query(archive))


def test_later_v2_correction_preserves_original_now_withdrawn_source_evidence():
    archive, context = mixed_archive(amendments=2)
    first_command, first_context = v2_basis(amendments=0)
    first = prepare(first_command, first_context, source_id=rf.Rf1086YearSourceId(identity(6602)),
                    confirmed_at=NOW - timedelta(days=1))
    second_command = replace(archive.source_history.year_sources[0].command,
        supersedes_source_id=first.source_id, supersedes_source_sha256=first.source_sha256,
        correction_reason='Use retained amendment history')
    second = prepare(second_command, context, source_id=rf.Rf1086YearSourceId(identity(6603)), previous=first)
    archive = with_sources(archive, (first, second))
    validate(archive)
    assert first.governance_receipts[0].register_observation.observation_id == archive.source_history.register_observations[0].observation_id
    assert rf.parse_rf1086_register_observation_withdrawal(archive.withdrawal_capture_records[0].snapshot_text).command.observation_id == first.governance_receipts[0].register_observation.observation_id


def test_capture_namespaces_do_not_impose_cross_family_key_uniqueness():
    archive, _ = mixed_archive()
    history = archive.source_history
    key = history.source_capture_records[0].idempotency_key
    archive = replace(archive, source_history=replace(history,
        observation_capture_records=(replace(history.observation_capture_records[0], idempotency_key=key),
                                     *history.observation_capture_records[1:])),
        withdrawal_capture_records=(replace(archive.withdrawal_capture_records[0], idempotency_key=key),
                                    *archive.withdrawal_capture_records[1:]))
    validate(archive)


def test_observation_key_uniqueness_is_actor_scoped():
    from talli_backend.shared.kernel import ActorId, ActorKind, UserId
    archive, _ = mixed_archive()
    history = archive.source_history
    command = replace(history.year_sources[0].command, actor_id=ActorId(ActorKind.USER, UserId(identity(9999))))
    other = observation(command, 0, 9998, NOW)
    capture = replace(capture_observation(other), idempotency_key=history.observation_capture_records[0].idempotency_key)
    archive = replace(archive, source_history=replace(history,
        register_observations=(*history.register_observations, other),
        observation_capture_records=(*history.observation_capture_records, capture)))
    validate(archive)


@pytest.mark.parametrize('family', ['source', 'observation', 'withdrawal'])
def test_same_actor_duplicate_key_in_one_family_is_rejected(family):
    archive, _ = mixed_archive(legacy=True)
    field = family + '_capture_records'
    target = archive if family == 'withdrawal' else archive.source_history
    records = getattr(target, field)
    target = replace(target, **{field: (records[0], replace(records[1], idempotency_key=records[0].idempotency_key), *records[2:])})
    if family != 'withdrawal': target = replace(archive, source_history=target)
    with pytest.raises(ValueError, match='^RF source history is inconsistent$'): validate(target)


@pytest.mark.parametrize('change', ['duplicate_source', 'duplicate_observation', 'duplicate_preview',
                                  'capture_mapping', 'capture_subclass', 'head_numeric', 'unknown_history'])
def test_history_rejects_duplicate_or_wrong_typed_records(change):
    archive, _ = mixed_archive(previews=True)
    history = archive.source_history
    if change == 'duplicate_source': history = replace(history, year_sources=history.year_sources * 2)
    elif change == 'duplicate_observation': history = replace(history, register_observations=history.register_observations * 2)
    elif change == 'duplicate_preview': history = replace(history, source_previews=history.source_previews * 2)
    elif change in ('capture_mapping', 'capture_subclass'):
        from dataclasses import fields
        row = history.source_capture_records[0]
        values = {field.name: getattr(row, field.name) for field in fields(row)}
        if change == 'capture_mapping': bad = values
        else:
            class Derived(rf.Rf1086ArchiveCaptureRecord): pass
            bad = Derived(**values)
        history = replace(history, source_capture_records=(bad,))
    elif change == 'head_numeric': history = replace(history, year_source_head=replace(history.year_source_head, version=1.0))
    else: history = None
    with pytest.raises(ValueError, match='^RF source history is inconsistent$'):
        validate(replace(archive, source_history=history))


def test_capture_order_is_not_source_ordinal_or_foreign_evidence_order():
    archive, _ = mixed_archive(legacy=True, previews=True)
    history = archive.source_history
    archive = replace(archive, source_history=replace(history,
        year_sources=tuple(reversed(history.year_sources)),
        source_capture_records=tuple(reversed(history.source_capture_records)),
        register_observations=tuple(reversed(history.register_observations)),
        observation_capture_records=tuple(reversed(history.observation_capture_records))),
        withdrawal_capture_records=tuple(reversed(archive.withdrawal_capture_records)))
    validate(archive)


def test_retained_observation_offset_and_raw_decimal_scale_are_not_rewritten():
    from datetime import timezone
    from decimal import Decimal
    from test_rf1086_register_observation import basis as register_basis
    archive, _ = mixed_archive('no_activity')
    command, context = register_basis()
    documents = tuple(replace(doc, created_at=doc.created_at.astimezone(timezone(timedelta(hours=-4))))
                      for doc in command.documents)
    command = replace(command, documents=documents,
        before=replace(command.before, share_capital=Decimal('60000.00')))
    context = replace(context, documents=documents)
    row = rf.prepare_rf1086_register_observation(command, context=context,
        observation_id=rf.Rf1086RegisterObservationId(identity(9996)), confirmed_at=NOW)
    capture = capture_observation(row)
    raw = json.dumps(json.loads(capture.snapshot_text), indent=1) + '\n'
    archive = replace(archive, source_history=replace(archive.source_history,
        register_observations=(row,), observation_capture_records=(replace(capture, snapshot_text=raw),)))
    validate(archive)
    assert archive.source_history.observation_capture_records[0].snapshot_text == raw
    assert '-04:00' in raw and '60000.00' in raw


def test_independent_historical_root_does_not_require_effective_instant_equality():
    archive, context = mixed_archive(amendments=1)
    history = archive.source_history
    original, effective = history.register_observations
    command = replace(original.command, effective_at=original.command.effective_at + timedelta(hours=1))
    verification = rf.Rf1086VerifiedRegisterObservationContext(command.actor_id, True,
        command.company_id, command.income_year, command.documents, True)
    changed = rf.prepare_rf1086_register_observation(command, context=verification,
        observation_id=original.observation_id, confirmed_at=original.confirmed_at)
    old_withdrawal = rf.parse_rf1086_register_observation_withdrawal(archive.withdrawal_capture_records[0].snapshot_text)
    receipt = withdraw(changed, 3001, old_withdrawal.withdrawn_at)
    chain = context.governance_projection.chains[0]
    link = replace(chain.amendments[0], target=register_fact(changed), withdrawal_sha256=receipt.withdrawal_sha256)
    chain = replace(chain, original_register_fact=register_fact(changed), amendments=(link,))
    wrapped = context.governance_receipts[0]
    context = replace(context, governance_receipts=(replace(wrapped,
        original=replace(wrapped.original, register_observation_sha256=changed.fact_sha256)),))
    archive = replace(archive, source_history=replace(history, register_observations=(changed, effective),
        observation_capture_records=(capture_observation(changed), capture_observation(effective))),
        withdrawal_capture_records=(capture_withdrawal(receipt),))
    archive = replace_projection(archive, context, (chain,))
    # Governance's actual correspondence contract is a local-date check, not
    # exact civil-time equality. This pure fixture does not authenticate its
    # opaque Governance labels; it establishes only retained RF consistency.
    assert changed.command.effective_at.date() == effective.command.effective_at.date()
    assert changed.command.effective_at != effective.command.effective_at
    validate(archive)
