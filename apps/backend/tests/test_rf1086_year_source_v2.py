"""Pure RF v2 evidence commitments; synthetic Governance labels confer no authority.

Register observations use the existing public constructor. Complete owner reads,
accepted-owner/current-head locks, withdrawal existence and original bytes remain
future workflow/database responsibilities, not facts established by these tests.
"""
from dataclasses import FrozenInstanceError, fields, replace
from datetime import timedelta, timezone
from hashlib import sha256
import json
from uuid import UUID

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId
from test_rf1086_source_production import source_case, source_for
from test_rf1086_year_source import NOW, SOURCE, basis as old_basis, prepare as old_prepare
from test_rf1086_register_observation import basis as observation_basis


CONFIRMED = NOW + timedelta(days=10, microseconds=123456)
CAPITAL = ('cash_issue', 'loss_covering_reduction')


def identity(number):
    return str(UUID(int=number))


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def projection(chains=(), *, company_id=None, income_year=None, original_sha='d' * 64):
    """Independent oracle for the documented public Governance manifest shape."""
    command, _ = old_basis()
    company_id = command.company_id if company_id is None else company_id
    income_year = command.income_year if income_year is None else income_year
    chains = tuple(sorted(chains, key=lambda row: row.receipt_id))
    scope = dict(company_id=company_id.value, income_year=income_year.value)
    descriptors = [dict(event_id=row.receipt_id, income_year=row.income_year.value,
        anchor_sha256=row.original_anchor_sha256, amendment_count=row.amendment_count,
        enumeration_sha256=row.enumeration_sha256) for row in chains]
    chain_sha = digest(['corporate-reporting-register-evidence-v1',
        dict(**scope, chain_count=len(chains), chains=descriptors)])
    combined_sha = digest(['corporate-reporting-register-evidence-projection-v1',
        dict(**scope, original_enumeration_sha256=original_sha, chain_enumeration_sha256=chain_sha)])
    return rf.Rf1086YearGovernanceProjectionV2(company_id, income_year, original_sha,
        chain_sha, combined_sha, chains, len(chains))


def register_fact(observation):
    return rf.Rf1086YearRegisterFactV2(observation.observation_id,
        observation.version, observation.fact_sha256)


def observation(command, event_index, number, confirmed_at):
    before, after = rf.rf1086_event_register_states(command.case, event_index)
    event = command.case.events[event_index]
    template, _ = observation_basis(event.type)
    documents = tuple(replace(doc, document_id=identity(5000 + event_index * 10 + index),
        company_id=command.company_id, created_at=NOW - timedelta(days=20),
        source_income_year=IncomeYear(2024)) for index, doc in enumerate(template.documents))
    record = replace(template, company_id=command.company_id, actor_id=command.actor_id,
        income_year=command.income_year, effective_at=event.timestamp, event_kind=event.type,
        before=before, after=after, documents=documents)
    context = rf.Rf1086VerifiedRegisterObservationContext(command.actor_id, True,
        command.company_id, command.income_year, documents, True)
    return rf.prepare_rf1086_register_observation(record, context=context,
        observation_id=rf.Rf1086RegisterObservationId(identity(number)), confirmed_at=confirmed_at)


def v2_basis(kind='cash_issue', *, amendments=0):
    case = source_case(kind)
    if kind == 'mixed':
        case = replace(case, share_snapshot=replace(case.share_snapshot, previous_paid_in_premium=0))
    old = source_for(case)
    command = old.command
    originals = {row.receipt_id: row for row in old.governance_receipts}
    chains, receipts = [], []
    for evidence in command.event_evidence:
        if evidence.governance_receipt_id is None:
            continue
        original = originals[evidence.governance_receipt_id]
        if original.event_type == 'dividend':
            receipts.append(rf.Rf1086YearGovernanceReceiptV2(original, None))
            continue
        index = evidence.event_index
        first = observation(command, index, 1000 + index * 100, NOW - timedelta(days=3))
        original = replace(original, register_observation_id=first.observation_id.value,
            register_observation_sha256=first.fact_sha256)
        current, links, previous = first, [], None
        for revision in range(1, amendments + 1):
            successor = observation(command, index, 1000 + index * 100 + revision,
                NOW + timedelta(hours=revision))
            head = rf.Rf1086YearGovernanceHeadV2(identity(2000 + index * 100 + revision),
                revision, digest(['amendment', index, revision]))
            links.append(rf.Rf1086YearGovernanceLinkV2(head, previous,
                identity(3000 + index * 100 + revision), digest(['withdrawal', index, revision]),
                register_fact(current), register_fact(successor), successor.confirmed_at))
            current, previous = successor, head
        original_time = NOW - timedelta(days=2)
        chain = rf.Rf1086YearGovernanceChainV2(original.receipt_id, command.company_id,
            command.income_year, original.event_type, original.finalization_sha256,
            digest(['anchor', index]), original_time, register_fact(first), tuple(links),
            amendments, digest(['trusted-owner-chain', index, amendments]), previous,
            register_fact(current), links[-1].recorded_at if links else original_time)
        chains.append(chain)
        receipts.append(rf.Rf1086YearGovernanceReceiptV2(original, current))
    # The fresh workflow must reread every effective RF original, in addition to
    # the old Governance/year evidence. Shared role documents are kept once.
    documents = {doc.document_id: doc for doc in command.documents}
    for receipt in receipts:
        if receipt.register_observation is not None:
            for doc in receipt.register_observation.command.documents:
                documents[doc.document_id] = rf.Rf1086YearDocumentEvidence(**{
                    field.name: getattr(doc, field.name) for field in fields(rf.Rf1086YearDocumentEvidence)})
    command = replace(command, documents=tuple(documents.values()))
    context = rf.Rf1086VerifiedYearSourceContextV2(command.actor_id, True,
        command.company_id, command.income_year, command.case.company,
        old.freshness.company_identity_sha256, command.documents, tuple(receipts), True,
        projection(chains, original_sha=old.freshness.governance_enumeration_sha256))
    return command, context


def prepare(command=None, context=None, **kwargs):
    if command is None:
        command, context = v2_basis()
    return rf.prepare_rf1086_year_source_v2(command, context=context,
        source_id=kwargs.pop('source_id', SOURCE),
        confirmed_at=kwargs.pop('confirmed_at', CONFIRMED), **kwargs)


def with_chain(context, chain):
    return replace(context, governance_projection=projection((chain,),
        original_sha=context.governance_projection.original_enumeration_sha256))


@pytest.mark.parametrize('kind', ['no_activity', 'formation', 'dividend', *CAPITAL, 'mixed'])
@pytest.mark.parametrize('amendments', [0, 1, 2])
def test_full_year_cases_preserve_case_and_request_but_bind_complete_new_evidence(kind, amendments):
    command, context = v2_basis(kind, amendments=amendments)
    request_sha = rf.rf1086_year_source_digest(command)
    source = prepare(command, context)
    assert source.version == 1
    assert source.case_sha256 == rf.rf1086_year_source_digest(command.case)
    assert source.command is command
    assert rf.rf1086_year_source_digest(source.command) == request_sha
    assert source.governance_projection == context.governance_projection
    assert all(row.amendment_count == amendments for row in source.governance_projection.chains)
    assert source.command.documents[0].source_income_year == IncomeYear(2024)
    rf.assert_rf1086_year_source_integrity_v2(source)
    rf.assert_rf1086_year_source_replay_v2(source, command)
    rf.assert_rf1086_year_source_fresh_v2(source, current_source_id=source.source_id,
        current_source_sha256=source.source_sha256, context=context)
    with pytest.raises(FrozenInstanceError):
        source.version = 42


def test_nominal_increase_does_not_invent_governance_producer_support():
    with pytest.raises(rf.Rf1086YearSourceError):
        prepare(*v2_basis('cash_nominal_increase'))


def test_amended_receipt_retains_original_and_uses_replacement_after_original_finalization():
    command, context = v2_basis(amendments=2)
    source = prepare(command, context)
    chain = source.governance_projection.chains[0]
    receipt = source.governance_receipts[0]
    assert receipt.original == context.governance_receipts[0].original
    assert receipt.original.register_observation_id == chain.original_register_fact.observation_id.value
    assert receipt.register_observation.observation_id == chain.effective_register_fact.observation_id
    assert receipt.register_observation.confirmed_at > chain.original_recorded_at
    assert receipt.register_observation.confirmed_at == chain.evidence_cutoff < source.confirmed_at
    assert chain.head == chain.amendments[-1].head


@pytest.mark.parametrize('kind', ['no_activity', 'formation', 'dividend', *CAPITAL, 'mixed'])
def test_new_codec_does_not_introduce_a_new_request_digest_for_identical_old_command(kind):
    command, context = v2_basis(kind)
    legacy_context = rf.Rf1086VerifiedYearSourceContext(context.actor_id, context.accepted_owner,
        context.company_id, context.income_year, context.company, context.company_identity_sha256,
        context.documents, tuple(row.original for row in context.governance_receipts),
        context.complete_governance_enumeration, context.governance_projection.original_enumeration_sha256)
    old = old_prepare(command, legacy_context, confirmed_at=CONFIRMED)
    new = prepare(command, context)
    assert old.command == new.command == command
    assert rf.rf1086_year_source_digest(old.command) == rf.rf1086_year_source_digest(new.command)
    assert old.case_sha256 == new.case_sha256
    assert old.source_sha256 != new.source_sha256
    assert old.version == new.version == 1


def test_empty_target_year_still_binds_off_year_complete_chain_history():
    command, context = v2_basis('no_activity')
    _, capital = v2_basis(amendments=2)
    chain = replace(capital.governance_projection.chains[0], income_year=IncomeYear(2024))
    populated = replace(context, governance_projection=projection((chain,)))
    empty, source = prepare(command, context), prepare(command, populated)
    assert source.governance_receipts == ()
    assert source.governance_projection.chain_count == 1
    assert source.case_sha256 == empty.case_sha256
    assert source.source_sha256 != empty.source_sha256
    with pytest.raises(rf.Rf1086YearSourceError):
        rf.assert_rf1086_year_source_fresh_v2(source, current_source_id=source.source_id,
            current_source_sha256=source.source_sha256, context=context)


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'extra_target_year', 'wrong_company',
    'wrong_year', 'wrong_type', 'original_reference', 'finalization', 'effective_reference', 'wrong_count'])
def test_target_year_receipts_and_chains_must_match_exactly(change):
    command, context = v2_basis(amendments=1)
    chain = context.governance_projection.chains[0]
    with pytest.raises(rf.Rf1086YearSourceError):
        if change == 'missing': context = replace(context, governance_projection=projection())
        elif change == 'duplicate': context = replace(context, governance_projection=projection((chain, chain)))
        elif change == 'extra_target_year': context = replace(context, governance_projection=projection((chain, replace(chain, receipt_id=identity(77)))))
        elif change == 'wrong_company': context = with_chain(context, replace(chain, company_id=CompanyId(identity(77))))
        elif change == 'wrong_year': context = with_chain(context, replace(chain, income_year=IncomeYear(2024)))
        elif change == 'wrong_type': context = with_chain(context, replace(chain, event_type='loss_covering_reduction'))
        elif change == 'original_reference': context = with_chain(context, replace(chain, original_register_fact=replace(chain.original_register_fact, fact_sha256='e' * 64)))
        elif change == 'finalization': context = with_chain(context, replace(chain, original_finalization_sha256='e' * 64))
        elif change == 'effective_reference': context = with_chain(context, replace(chain, effective_register_fact=chain.original_register_fact))
        elif change == 'wrong_count': context = replace(context, governance_projection=replace(context.governance_projection, chain_count=0))
        prepare(command, context)


@pytest.mark.parametrize('change', ['missing_head', 'head_revision', 'head_hash', 'missing_link',
    'wrong_previous', 'wrong_target', 'reactivated_original', 'same_replacement', 'duplicate_id',
    'duplicate_withdrawal', 'nonmonotonic', 'cutoff', 'before_original', 'bool_count', 'negative_count'])
def test_compact_chain_is_linear_and_never_reactivates_an_ancestor(change):
    command, context = v2_basis(amendments=2)
    chain = context.governance_projection.chains[0]
    first, last = chain.amendments
    with pytest.raises(rf.Rf1086YearSourceError):
        if change == 'missing_head': chain = replace(chain, head=None)
        elif change == 'head_revision': chain = replace(chain, head=replace(chain.head, revision=3))
        elif change == 'head_hash': chain = replace(chain, head=replace(chain.head, amendment_sha256='f' * 64))
        elif change == 'missing_link': chain = replace(chain, amendments=(last,))
        elif change == 'wrong_previous': chain = replace(chain, amendments=(first, replace(last, previous_head=None)))
        elif change == 'wrong_target': chain = replace(chain, amendments=(first, replace(last, target=chain.original_register_fact)))
        elif change == 'reactivated_original': chain = replace(chain, amendments=(first, replace(last, replacement=chain.original_register_fact)), effective_register_fact=chain.original_register_fact)
        elif change == 'same_replacement': chain = replace(chain, amendments=(first, replace(last, replacement=last.target)), effective_register_fact=last.target)
        elif change == 'duplicate_id': chain = replace(chain, amendments=(first, replace(last, head=replace(last.head, amendment_id=first.head.amendment_id))), head=replace(last.head, amendment_id=first.head.amendment_id))
        elif change == 'duplicate_withdrawal': chain = replace(chain, amendments=(first, replace(last, withdrawal_id=first.withdrawal_id)))
        elif change == 'nonmonotonic': chain = replace(chain, amendments=(first, replace(last, recorded_at=first.recorded_at)), evidence_cutoff=first.recorded_at)
        elif change == 'cutoff': chain = replace(chain, evidence_cutoff=chain.evidence_cutoff + timedelta(microseconds=1))
        elif change == 'before_original': chain = replace(chain, original_recorded_at=first.recorded_at)
        elif change == 'bool_count': chain = replace(chain, amendment_count=True)
        elif change == 'negative_count': chain = replace(chain, amendment_count=-1)
        prepare(command, with_chain(context, chain))


@pytest.mark.parametrize('relation', ['equal_source', 'after_source', 'observation_after_cutoff'])
def test_exact_microsecond_cutoff_precedes_source_and_bounds_effective_observation(relation):
    command, context = v2_basis(amendments=1)
    chain = context.governance_projection.chains[0]
    with pytest.raises(rf.Rf1086YearSourceError):
        if relation == 'observation_after_cutoff':
            link = replace(chain.amendments[0], recorded_at=chain.evidence_cutoff - timedelta(microseconds=1))
            context = with_chain(context, replace(chain, amendments=(link,), evidence_cutoff=link.recorded_at))
            prepare(command, context)
        else:
            prepare(command, context, confirmed_at=chain.evidence_cutoff -
                (timedelta(microseconds=1) if relation == 'after_source' else timedelta()))


@pytest.mark.parametrize('change', ['company', 'year', 'date', 'kind', 'states', 'hash'])
def test_full_effective_observation_must_match_event_not_merely_reference_labels(change):
    command, context = v2_basis()
    receipt = context.governance_receipts[0]
    observed = receipt.register_observation
    record = observed.command
    if change == 'company': record = replace(record, company_id=CompanyId(identity(81)), documents=tuple(replace(doc, company_id=CompanyId(identity(81))) for doc in record.documents))
    elif change == 'year': record = replace(record, income_year=IncomeYear(2024), effective_at=record.effective_at.replace(year=2024))
    elif change == 'date': record = replace(record, effective_at=record.effective_at + timedelta(days=1))
    elif change in ('kind', 'states'):
        wrong, _ = observation_basis('loss_covering_reduction' if change == 'kind' else 'cash_issue')
        record = replace(record, event_kind=wrong.event_kind, before=wrong.before, after=wrong.after)
    if change != 'hash':
        verified = rf.Rf1086VerifiedRegisterObservationContext(record.actor_id, True, record.company_id,
            record.income_year, record.documents, True)
        observed = rf.prepare_rf1086_register_observation(record, context=verified,
            observation_id=observed.observation_id, confirmed_at=observed.confirmed_at)
    else:
        observed = replace(observed, fact_sha256='f' * 64)
    # Rebind every copied reference so failure cannot be only a stale label.
    original = replace(receipt.original, register_observation_sha256=observed.fact_sha256)
    receipt = replace(receipt, original=original, register_observation=observed)
    chain = context.governance_projection.chains[0]
    chain = replace(chain, original_register_fact=register_fact(observed), effective_register_fact=register_fact(observed))
    context = with_chain(replace(context, governance_receipts=(receipt,)), chain)
    with pytest.raises(rf.Rf1086YearSourceError):
        prepare(command, context)


@pytest.mark.parametrize('changed', ['original_enum', 'chain_enum', 'anchor', 'withdrawal',
    'withdrawal_id', 'original_time', 'intermediate_fact', 'head',
    'company_identity', 'document', 'receipt'])
def test_freshness_binds_trusted_labels_without_claiming_their_external_authority(changed):
    command, context = v2_basis(amendments=2)
    source = prepare(command, context)
    chain = context.governance_projection.chains[0]
    if changed == 'original_enum': context = replace(context, governance_projection=projection((chain,), original_sha='e' * 64))
    elif changed == 'chain_enum': context = with_chain(context, replace(chain, enumeration_sha256='e' * 64))
    elif changed == 'anchor': context = with_chain(context, replace(chain, original_anchor_sha256='e' * 64))
    elif changed == 'withdrawal': context = with_chain(context, replace(chain, amendments=(replace(chain.amendments[0], withdrawal_sha256='e' * 64), chain.amendments[1])))
    elif changed == 'withdrawal_id': context = with_chain(context, replace(chain, amendments=(replace(chain.amendments[0], withdrawal_id=identity(888)), chain.amendments[1])))
    elif changed == 'original_time': context = with_chain(context, replace(chain, original_recorded_at=chain.original_recorded_at + timedelta(microseconds=1)))
    elif changed == 'intermediate_fact':
        middle = replace(chain.amendments[0].replacement, fact_sha256='e' * 64)
        context = with_chain(context, replace(chain, amendments=(replace(chain.amendments[0], replacement=middle), replace(chain.amendments[1], target=middle))))
    elif changed == 'head':
        head = replace(chain.head, amendment_sha256='e' * 64)
        context = with_chain(context, replace(chain, head=head, amendments=(chain.amendments[0], replace(chain.amendments[1], head=head))))
    elif changed == 'company_identity': context = replace(context, company_identity_sha256='e' * 64)
    elif changed == 'document': context = replace(context, documents=(replace(context.documents[0], metadata_sha256='e' * 64),))
    elif changed == 'receipt': context = replace(context, governance_receipts=(replace(context.governance_receipts[0], original=replace(context.governance_receipts[0].original, active=False)),))
    with pytest.raises(rf.Rf1086YearSourceError):
        rf.assert_rf1086_year_source_fresh_v2(source, current_source_id=source.source_id,
            current_source_sha256=source.source_sha256, context=context)
    if changed not in ('document', 'receipt'):
        renewed = prepare(command, context)
        assert renewed.case_sha256 == source.case_sha256
        assert renewed.source_sha256 != source.source_sha256
        assert renewed.command == source.command


@pytest.mark.parametrize('change', ['owner', 'actor', 'company', 'year', 'incomplete', 'missing_receipt', 'duplicate_receipt', 'missing_observation', 'dividend_observation'])
def test_verified_context_and_complete_event_receipts_cannot_be_inferred(change):
    command, context = v2_basis('dividend' if change == 'dividend_observation' else 'cash_issue')
    with pytest.raises(rf.Rf1086YearSourceError):
        if change == 'owner': context = replace(context, accepted_owner=False)
        elif change == 'actor': context = replace(context, actor_id=ActorId(ActorKind.USER, UserId(identity(81))))
        elif change == 'company': context = replace(context, company_id=CompanyId(identity(81)))
        elif change == 'year': context = replace(context, income_year=IncomeYear(2024))
        elif change == 'incomplete': context = replace(context, complete_governance_enumeration=False)
        elif change == 'missing_receipt': context = replace(context, governance_receipts=())
        elif change == 'duplicate_receipt': context = replace(context, governance_receipts=context.governance_receipts * 2)
        elif change == 'missing_observation': context = replace(context, governance_receipts=(replace(context.governance_receipts[0], register_observation=None),))
        elif change == 'dividend_observation':
            _, capital = v2_basis()
            context = replace(context, governance_receipts=(replace(context.governance_receipts[0], register_observation=capital.governance_receipts[0].register_observation),))
        prepare(command, context)


@pytest.mark.parametrize('previous_codec', [1, 2])
def test_explicit_correction_advances_source_ordinal_without_mutating_v1_history(previous_codec):
    command, context = v2_basis('no_activity')
    previous = old_prepare(*old_basis()) if previous_codec == 1 else prepare(command, context)
    before = (rf.serialize_rf1086_year_source if previous_codec == 1 else rf.serialize_rf1086_year_source_v2)(previous)
    correction = replace(command, supersedes_source_id=previous.source_id,
        supersedes_source_sha256=previous.source_sha256, correction_reason='  Exact reviewed correction — årsak  ')
    next_source = prepare(correction, context, previous=previous,
        source_id=rf.Rf1086YearSourceId(identity(901)), confirmed_at=CONFIRMED + timedelta(days=1))
    assert next_source.version == 2
    assert next_source.case_sha256 == previous.case_sha256
    assert next_source.command.correction_reason == correction.correction_reason
    assert next_source.command.supersedes_source_sha256 == previous.source_sha256
    assert (rf.serialize_rf1086_year_source if previous_codec == 1 else rf.serialize_rf1086_year_source_v2)(previous) == before
    (rf.assert_rf1086_year_source_replay if previous_codec == 1 else rf.assert_rf1086_year_source_replay_v2)(previous, previous.command)


@pytest.mark.parametrize('change', ['missing_previous', 'missing_link', 'wrong_hash', 'wrong_id', 'empty_reason', 'same_id', 'same_time', 'foreign_company'])
def test_v1_to_v2_is_an_explicit_correction_not_a_silent_codec_upgrade(change):
    previous = old_prepare(*old_basis())
    command, context = v2_basis('no_activity')
    command = replace(command, supersedes_source_id=previous.source_id,
        supersedes_source_sha256=previous.source_sha256, correction_reason='Reviewed change')
    target = rf.Rf1086YearSourceId(identity(902))
    instant = CONFIRMED
    with pytest.raises(rf.Rf1086YearSourceError):
        if change == 'missing_previous': previous = None
        elif change == 'missing_link': command = replace(command, supersedes_source_id=None)
        elif change == 'wrong_hash': command = replace(command, supersedes_source_sha256='f' * 64)
        elif change == 'wrong_id': command = replace(command, supersedes_source_id=target)
        elif change == 'empty_reason': command = replace(command, correction_reason=' \n ')
        elif change == 'same_id': target = previous.source_id
        elif change == 'same_time': instant = previous.confirmed_at
        elif change == 'foreign_company': previous = replace(previous, company_id=CompanyId(identity(81)))
        prepare(command, context, previous=previous, source_id=target, confirmed_at=instant)


@pytest.mark.parametrize('change', ['actor', 'company', 'year', 'body', 'reason'])
def test_replay_uses_unchanged_exact_command_digest_and_never_a_new_evidence_context(change):
    command, context = v2_basis()
    source = prepare(command, context)
    if change == 'actor': command = replace(command, actor_id=ActorId(ActorKind.USER, UserId(identity(81))))
    elif change == 'company': command = replace(command, company_id=CompanyId(identity(81)))
    elif change == 'year': command = replace(command, income_year=IncomeYear(2024))
    elif change == 'body': command = replace(command, identities_reviewed=False)
    elif change == 'reason': command = replace(command, correction_reason='new reason')
    with pytest.raises(rf.Rf1086YearSourceError, match='idempotency_conflict'):
        rf.assert_rf1086_year_source_replay_v2(source, command)


def test_new_commitment_instants_require_canonical_utc_and_preserve_microseconds():
    command, context = v2_basis(amendments=1)
    source = prepare(command, context)
    offset = timezone(timedelta(hours=-4, seconds=-30))
    chain = context.governance_projection.chains[0]
    equivalent = replace(chain, original_recorded_at=chain.original_recorded_at.astimezone(offset),
        evidence_cutoff=chain.evidence_cutoff.astimezone(offset),
        amendments=tuple(replace(link, recorded_at=link.recorded_at.astimezone(offset)) for link in chain.amendments))
    with pytest.raises(rf.Rf1086YearSourceError):
        prepare(command, with_chain(context, equivalent))
    with pytest.raises(rf.Rf1086YearSourceError):
        prepare(command, context, confirmed_at=CONFIRMED.astimezone(offset))
    assert source.confirmed_at.microsecond == 123456
    assert source.confirmed_at.tzinfo is timezone.utc


def test_new_codec_does_not_normalize_legacy_document_offsets_or_request_digest():
    command, context = v2_basis('no_activity')
    source = prepare(command, context)
    offset = timezone(timedelta(hours=-4, seconds=-30))
    doc = replace(command.documents[0], created_at=command.documents[0].created_at.astimezone(offset))
    shifted_command = replace(command, documents=(doc,))
    shifted_context = replace(context, documents=(doc,))
    shifted = prepare(shifted_command, shifted_context)
    assert shifted.command.documents[0].created_at.utcoffset() == offset.utcoffset(None)
    assert rf.rf1086_year_source_digest(shifted_command) != rf.rf1086_year_source_digest(command)
    assert shifted.source_sha256 != source.source_sha256


def test_existing_observation_offset_is_preserved_while_cutoff_compares_instants():
    command, context = v2_basis(amendments=1)
    receipt = context.governance_receipts[0]
    observed = receipt.register_observation
    offset = timezone(timedelta(hours=5, minutes=30))
    shifted = replace(observed, confirmed_at=observed.confirmed_at.astimezone(offset))
    rf.assert_rf1086_register_observation_integrity(shifted)
    context = replace(context, governance_receipts=(replace(receipt, register_observation=shifted),))
    source = prepare(command, context)
    restored = rf.parse_rf1086_year_source_v2(rf.serialize_rf1086_year_source_v2(source))
    assert restored.governance_receipts[0].register_observation.confirmed_at.isoformat() == shifted.confirmed_at.isoformat()
    assert shifted.confirmed_at == source.governance_projection.chains[0].evidence_cutoff


def test_v1_correction_ordinal_and_offset_predecessor_remain_frozen_when_v2_advances():
    command, old_context = old_basis()
    first = old_prepare(command, old_context)
    corrected = replace(command, supersedes_source_id=first.source_id,
        supersedes_source_sha256=first.source_sha256, correction_reason='First correction')
    offset = timezone(timedelta(hours=-4))
    previous = old_prepare(corrected, old_context, previous=first,
        source_id=rf.Rf1086YearSourceId(identity(920)),
        confirmed_at=(NOW + timedelta(days=1)).astimezone(offset))
    original_bytes = rf.serialize_rf1086_year_source(previous)
    command, context = v2_basis('no_activity')
    command = replace(command, supersedes_source_id=previous.source_id,
        supersedes_source_sha256=previous.source_sha256, correction_reason='Explicit v2 successor')
    successor = prepare(command, context, previous=previous,
        source_id=rf.Rf1086YearSourceId(identity(921)))
    assert successor.version == 3
    assert previous.version == 2
    assert previous.confirmed_at.utcoffset() == timedelta(hours=-4)
    assert rf.serialize_rf1086_year_source(previous) == original_bytes
    rf.assert_rf1086_year_source_replay(previous, previous.command)


@pytest.mark.parametrize('change', ['version', 'company', 'year', 'actor', 'time', 'case',
    'source', 'command', 'freshness'])
def test_typed_snapshot_integrity_binds_identity_time_case_command_and_freshness(change):
    source = prepare(*v2_basis(amendments=2))
    if change == 'version': source = replace(source, version=True)
    elif change == 'company': source = replace(source, company_id=CompanyId(identity(88)))
    elif change == 'year': source = replace(source, income_year=IncomeYear(2024))
    elif change == 'actor': source = replace(source, confirmed_by=ActorId(ActorKind.USER, UserId(identity(88))))
    elif change == 'time': source = replace(source, confirmed_at=source.confirmed_at + timedelta(microseconds=1))
    elif change == 'case': source = replace(source, case_sha256='f' * 64)
    elif change == 'source': source = replace(source, source_id=rf.Rf1086YearSourceId(identity(88)))
    elif change == 'command': source = replace(source, command=replace(source.command, identities_reviewed=False))
    elif change == 'freshness': source = replace(source, freshness=replace(source.freshness, company_identity_sha256='f' * 64))
    with pytest.raises(rf.Rf1086YearSourceError):
        rf.assert_rf1086_year_source_integrity_v2(source)


@pytest.mark.parametrize('change', ['status', 'metadata', 'content', 'missing_role_document'])
def test_effective_register_originals_are_exactly_covered_by_current_source_context(change):
    command, context = v2_basis(amendments=1)
    # Mutate both source command and supplied context so the old source/context
    # equality check cannot mask missing exact effective-observation evidence.
    docs = list(command.documents)
    if change == 'status': docs[-1] = replace(docs[-1], integrity_status='stored')
    elif change == 'metadata': docs[-1] = replace(docs[-1], metadata_sha256='f' * 64)
    elif change == 'content': docs[-1] = replace(docs[-1], content_sha256='f' * 64, content_version_sha256='f' * 64)
    elif change == 'missing_role_document': docs.pop()
    with pytest.raises(rf.Rf1086YearSourceError):
        prepare(replace(command, documents=tuple(docs)), replace(context, documents=tuple(docs)))


def test_current_accepted_owner_can_check_historical_source_without_rewriting_creator():
    command, context = v2_basis()
    source = prepare(command, context)
    successor_owner = ActorId(ActorKind.USER, UserId(identity(99)))
    rf.assert_rf1086_year_source_fresh_v2(source, current_source_id=source.source_id,
        current_source_sha256=source.source_sha256, context=replace(context, actor_id=successor_owner))
    assert source.confirmed_by == command.actor_id != successor_owner
