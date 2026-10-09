"""Exercise the public pure seam; no storage, authorization or RF proof supplied."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from talli_backend.modules.corporate_governance import public as gov
from talli_backend.modules.corporate_governance.service import CorporateGovernanceService
from talli_backend.shared.kernel import ActorId, ActorKind, UserId
from test_corporate_governance_supported_events import command, document, reduction_facts, source

UTC = timezone.utc
NOW = datetime(2026, 10, 9, 12, 30, 45, 123456, tzinfo=UTC)
ERROR = gov.CorporateRegisterEvidenceAmendmentError


def identifier(number):
    return f'90000000-0000-0000-0000-{number:012d}'


def fixture():
    kind = gov.SupportedCorporateEvidenceKind
    docs = (document(kind.SIGNED_DECISION, 1), document(kind.AMENDED_ARTICLES, 2), document(kind.REGISTRATION_RECEIPT, 3))
    cmd = command(kind=gov.SupportedCorporateEventKind.LOSS_COVERAGE_CAPITAL_REDUCTION,
        phase=gov.SupportedCorporateEventPhase.REGISTERED, facts=reduction_facts(), documents=docs,
        shareholder_register_fact=source(1))
    original = gov.RecordedSupportedCorporateEvent(CorporateGovernanceService().prepare_supported_event(cmd),
        gov.AccountingEntryReference(identifier(1)), None, None, NOW, False)
    anchor = gov.anchor_supported_corporate_event_evidence(original, original_actor_id=cmd.actor_id.subject)
    memo = document(kind.CORRECTION_MEMO, 4)
    request = gov.AmendSupportedCorporateRegisterEvidence(cmd.company_id, cmd.income_year, cmd.actor_id,
        cmd.event_id,
        anchor.anchor_sha256, None, gov.CorporateRegisterWithdrawalReference(gov.CorporateSourceReference(identifier(2)), 'c' * 64, source(1)),
        source(2), memo, '  Feil original – ø 😀 a\u030a.\n')
    originals = tuple(gov.CorporateDocumentOriginalCommitment(gov.CorporateSourceReference(identifier(10 + i)),
        doc.document_id, cmd.company_id, cmd.income_year, doc.revision, 'd' * 64, doc.content_sha256, 120,
        NOW + timedelta(seconds=1)) for i, doc in enumerate((*docs, memo)))
    receipt = gov.prepare_supported_corporate_register_evidence_amendment(request, anchor=anchor,
        amendment_id=gov.CorporateRegisterEvidenceAmendmentId(identifier(3)), recorded_at=NOW + timedelta(seconds=2), originals=originals)
    return anchor, request, originals, receipt


def follow(receipt, *, previous=None, actor=None):
    anchor = receipt.anchor
    cmd = replace(receipt.command, actor_id=actor or receipt.command.actor_id,
        expected_head=receipt.head,
        withdrawal=gov.CorporateRegisterWithdrawalReference(gov.CorporateSourceReference(identifier(4)), 'e' * 64, receipt.command.replacement),
        replacement=source(3))
    return gov.prepare_supported_corporate_register_evidence_amendment(cmd, anchor=anchor,
        amendment_id=gov.CorporateRegisterEvidenceAmendmentId(identifier(5)), recorded_at=receipt.recorded_at + timedelta(microseconds=1),
        originals=receipt.originals, previous=(receipt,) if previous is None else previous)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def recommit(value):
    """Make adversarial envelopes hash-consistent; shape validation must still fail."""
    row = value['amendment']
    row['request_sha256'] = digest(['corporate-register-evidence-amendment-request-v1', row['command']])
    body = {key: item for key, item in row.items() if key != 'amendment_sha256'}
    row['amendment_sha256'] = digest(['corporate-register-evidence-amendment-v1', body])
    return dumps(value)


def test_canonical_roundtrip_immutable_anchor_and_original_hashes_unchanged():
    anchor, cmd, originals, receipt = fixture()
    before = (anchor.original.event.facts_sha256, anchor.original.finalization_sha256, anchor.original)
    encoded = gov.serialize_corporate_register_evidence_amendment(receipt)
    assert 'idempotency' not in encoded and 'correlation' not in encoded
    assert gov.parse_corporate_register_evidence_amendment(encoded) == receipt
    assert gov.serialize_corporate_register_evidence_amendment(gov.parse_corporate_register_evidence_amendment(encoded)) == encoded
    assert '\\n' in encoded and 'ø 😀 a\u030a' in encoded
    assert before == (anchor.original.event.facts_sha256, anchor.original.finalization_sha256, anchor.original)
    assert receipt.command.reason == cmd.reason
    with pytest.raises(FrozenInstanceError): receipt.revision = 2
    with pytest.raises(TypeError): anchor.original.event.canonical_facts['incomeYear'] = 2025
    with pytest.raises(FrozenInstanceError): originals[0].byte_length = 20


def test_fixed_original_and_v1_amendment_digest_vectors():
    anchor, _, _, receipt = fixture()
    assert (anchor.original.event.facts_sha256, anchor.original.finalization_sha256) == (
        '970c562ebd94671205740d685f5419f7a08f781430226fca207b25f682248444',
        '5fd3d02c4296e02397886de500c32f5735465ca90d36cfa59dd5ac17723b26a1')
    assert (anchor.anchor_sha256, receipt.request_sha256, receipt.amendment_sha256) == (
        '6045257ee43debca3771af735d9bfe62bb847cfc7f9e40245f82b82f30a21046',
        '2f25beadbae92bbb5640872ad01ec154982736f7fceb80b9bcd9e0a6448c0027',
        '5263fd822d863d3140657995d5ee6816bd484ee6c0f261a480401e458c0e949d')
    assert hashlib.sha256(gov.serialize_corporate_register_evidence_amendment(receipt).encode()).hexdigest() == 'd60985061b313e6a47c07e05ac44ca1a3509e182cf79220b2a5a39110f4ce88f'


def test_anchor_binds_original_actor_recording_time_and_economics_without_rewriting_old_hash():
    anchor, _, _, _ = fixture()
    other = gov.anchor_supported_corporate_event_evidence(anchor.original, original_actor_id=UserId(identifier(20)))
    later = gov.anchor_supported_corporate_event_evidence(replace(anchor.original, recorded_at=NOW + timedelta(microseconds=1)), original_actor_id=anchor.original_actor_id)
    assert len({anchor.anchor_sha256, other.anchor_sha256, later.anchor_sha256}) == 3
    assert anchor.original.finalization_sha256 == other.original.finalization_sha256 == later.original.finalization_sha256
    # A caller can supply another actor; only the future owned projection proves provenance.
    assert other.original_actor_id != anchor.original_actor_id


def test_aware_equivalent_offsets_canonicalize_at_microsecond_precision():
    anchor, cmd, originals, receipt = fixture(); offset = timezone(timedelta(hours=-4))
    at = receipt.recorded_at.astimezone(offset)
    transformed = gov.prepare_supported_corporate_register_evidence_amendment(cmd, anchor=anchor,
        amendment_id=receipt.amendment_id, recorded_at=at,
        originals=tuple(replace(item, retained_at=item.retained_at.astimezone(offset)) for item in originals))
    assert transformed == receipt and gov.serialize_corporate_register_evidence_amendment(transformed) == gov.serialize_corporate_register_evidence_amendment(receipt)
    changed = gov.prepare_supported_corporate_register_evidence_amendment(cmd, anchor=anchor,
        amendment_id=receipt.amendment_id, recorded_at=receipt.recorded_at + timedelta(microseconds=1), originals=originals)
    assert changed.amendment_sha256 != receipt.amendment_sha256


def test_linear_chain_preserves_base_and_allows_new_owner_without_claiming_live_authority():
    anchor, _, _, first = fixture()
    actor = ActorId(ActorKind.USER, UserId(identifier(21)))
    second = follow(first, actor=actor)
    empty = gov.derive_corporate_register_evidence_chain(anchor, amendments=())
    chain = gov.derive_corporate_register_evidence_chain(anchor, amendments=(first, second))
    assert empty.head is None and empty.effective_register_fact == first.command.withdrawal.target
    assert chain.anchor == anchor and chain.head == second.head
    assert chain.effective_register_fact == second.command.replacement
    assert chain.amendments == (first, second) and second.command.actor_id != first.command.actor_id
    assert second.anchor.original_actor_id == first.anchor.original_actor_id
    # A prefix remains internally valid. It is not a certificate of full enumeration.
    assert gov.derive_corporate_register_evidence_chain(anchor, amendments=(first,)).head == first.head


@pytest.mark.parametrize('history', ['missing_first', 'reversed', 'duplicate', 'list'])
def test_chain_rejects_orphans_order_changes_duplicates_and_mutable_history(history):
    anchor, _, _, first = fixture(); second = follow(first)
    rows = {'missing_first':(second,), 'reversed':(second,first), 'duplicate':(first,first), 'list':[first]}[history]
    with pytest.raises(ERROR): gov.derive_corporate_register_evidence_chain(anchor, amendments=rows)


@pytest.mark.parametrize('change', ['fork', 'skip_revision', 'wrong_previous_hash', 'wrong_target', 'reused_target', 'reused_withdrawal', 'same_time'])
def test_preparation_rejects_invalid_next_edge(change):
    _, _, _, first = fixture(); second = follow(first); cmd = second.command; at = second.recorded_at
    if change == 'fork': cmd = replace(cmd, expected_head=None)
    elif change == 'skip_revision': cmd = replace(cmd, expected_head=replace(first.head, revision=3))
    elif change == 'wrong_previous_hash': cmd = replace(cmd, expected_head=replace(first.head, amendment_sha256='0'*64))
    elif change == 'wrong_target': cmd = replace(cmd, withdrawal=replace(cmd.withdrawal, target=source(8)))
    elif change == 'reused_target': cmd = replace(cmd, replacement=first.command.withdrawal.target)
    elif change == 'reused_withdrawal': cmd = replace(cmd, withdrawal=replace(cmd.withdrawal, withdrawal_id=first.command.withdrawal.withdrawal_id))
    else: at = first.recorded_at
    with pytest.raises(ERROR): gov.prepare_supported_corporate_register_evidence_amendment(cmd, anchor=first.anchor,
        amendment_id=second.amendment_id, recorded_at=at, originals=second.originals, previous=(first,))


@pytest.mark.parametrize('field,value', [('reason','changed'), ('reason','  Feil original – ø 😀 å.\n'),
    ('expected_anchor_sha256','f'*64), ('replacement',source(7)), ('actor_id',ActorId(ActorKind.USER,UserId(identifier(23))))])
def test_replay_binds_exact_actor_scope_and_business_request(field, value):
    _, cmd, _, receipt = fixture()
    gov.assert_corporate_register_evidence_amendment_replay(receipt, cmd)
    with pytest.raises(ERROR): gov.assert_corporate_register_evidence_amendment_replay(receipt, replace(cmd, **{field:value}))


@pytest.mark.parametrize('reason', ['', '  \n', '\x00', '\ud800', 'x'*1001, True, 4, None])
def test_request_rejects_invalid_reason_primitives_and_unicode(reason):
    _, cmd, _, _ = fixture()
    with pytest.raises(ERROR): gov.corporate_register_evidence_amendment_request_digest(replace(cmd, reason=reason))


@pytest.mark.parametrize('reason', ['x', ' x\t\r\n ', '\u2028\u2029x', '😀'*1000, '\x01x', 'a\u030a'])
def test_exact_valid_unicode_reason_is_not_normalized(reason):
    anchor, cmd, originals, receipt = fixture(); cmd = replace(cmd, reason=reason)
    result = gov.prepare_supported_corporate_register_evidence_amendment(cmd, anchor=anchor,
        amendment_id=receipt.amendment_id, recorded_at=receipt.recorded_at, originals=originals)
    assert gov.parse_corporate_register_evidence_amendment(gov.serialize_corporate_register_evidence_amendment(result)).command.reason == reason


@pytest.mark.parametrize('change', ['omitted', 'duplicate', 'wrong_company', 'wrong_revision', 'wrong_content', 'wrong_metadata', 'same_original_id', 'late', 'bool_length'])
def test_retained_original_commitments_cover_exact_frozen_documents_and_memo(change):
    anchor, cmd, originals, receipt = fixture(); altered = originals
    if change == 'omitted': altered = originals[:-1]
    elif change == 'duplicate': altered += (originals[0],)
    else:
        updates = {'wrong_company':dict(company_id=type(cmd.company_id)(identifier(9))), 'wrong_revision':dict(revision=2),
            'wrong_content':dict(content_sha256='0'*64), 'wrong_metadata':dict(metadata_sha256='BAD'),
            'same_original_id':dict(original_id=originals[1].original_id), 'late':dict(retained_at=receipt.recorded_at+timedelta(microseconds=1)),
            'bool_length':dict(byte_length=True)}[change]
        altered = (replace(originals[0], **updates),)+originals[1:]
    with pytest.raises(ERROR): gov.prepare_supported_corporate_register_evidence_amendment(cmd, anchor=anchor,
        amendment_id=receipt.amendment_id, recorded_at=receipt.recorded_at, originals=altered)


def test_additional_replacement_originals_are_bound_without_claiming_authoritative_coverage():
    anchor, cmd, originals, receipt = fixture()
    extra = replace(originals[0], document_id=gov.DocumentReference(identifier(80)),
        original_id=gov.CorporateSourceReference(identifier(81)), source_income_year=type(cmd.income_year)(2025))
    result = gov.prepare_supported_corporate_register_evidence_amendment(cmd, anchor=anchor,
        amendment_id=receipt.amendment_id, recorded_at=receipt.recorded_at, originals=originals+(extra,))
    assert extra in result.originals and result.amendment_sha256 != receipt.amendment_sha256
    assert gov.parse_corporate_register_evidence_amendment(gov.serialize_corporate_register_evidence_amendment(result)) == result


@pytest.mark.parametrize('target,field,value', [
    ('receipt','revision',True), ('receipt','revision',1.0), ('receipt','revision',0), ('receipt','request_sha256','A'*64),
    ('receipt','recorded_at','2026-10-09T12:30:47.123456'), ('receipt','recorded_at','2026-10-09T08:30:47.123456-04:00'),
    ('command','income_year',True), ('command','reason','\ud800'), ('command','reason','\x00'),
    ('replacement','revision',True), ('replacement','revision',1.0), ('replacement','revision','1'),
    ('replacement','fact_sha256','B'*64), ('replacement','record_id','bad'),
    ('original','byte_length',False), ('original','revision',True), ('original','source_income_year',2026.0),
])
def test_hash_consistent_malformed_encoded_primitives_are_rejected(target, field, value):
    _, _, _, receipt = fixture(); payload = json.loads(gov.serialize_corporate_register_evidence_amendment(receipt))
    row = payload['amendment']
    destination = {'receipt':row,'command':row['command'],'replacement':row['command']['replacement'],'original':row['originals'][0]}[target]
    destination[field] = value
    encoded = json.dumps(payload) if value == '\ud800' or field == 'request_sha256' else recommit(payload)
    with pytest.raises(ERROR): gov.parse_corporate_register_evidence_amendment(encoded)


@pytest.mark.parametrize('scope', ['envelope','receipt','command','actor','head','withdrawal','source','document','anchor','original','canonical','commitment'])
@pytest.mark.parametrize('attack', ['extra','missing'])
def test_codec_rejects_unknown_and_missing_fields_at_every_fixed_shape(scope, attack):
    _, _, _, first = fixture(); receipt = follow(first)
    payload = json.loads(gov.serialize_corporate_register_evidence_amendment(receipt)); row=payload['amendment']; cmd=row['command']
    target = {'envelope':payload,'receipt':row,'command':cmd,'actor':cmd['actor_id'],'head':cmd['expected_head'],
        'withdrawal':cmd['withdrawal'],'source':cmd['replacement'],'document':cmd['correction_memo'],
        'anchor':row['anchor'],'original':row['anchor']['original'],'canonical':row['anchor']['original']['canonicalFacts'],
        'commitment':row['originals'][0]}[scope]
    if attack == 'extra': target['unrecognized'] = True
    else: target.pop(next(iter(target)))
    with pytest.raises(ERROR): gov.parse_corporate_register_evidence_amendment(dumps(payload))


@pytest.mark.parametrize('attack', ['duplicate_top','duplicate_nested','whitespace','nan','wrong_codec','truncated','array'])
def test_codec_rejects_duplicate_keys_and_noncanonical_encoding(attack):
    _, _, _, receipt = fixture(); encoded = gov.serialize_corporate_register_evidence_amendment(receipt)
    if attack == 'duplicate_top': encoded = encoded[:-1] + ',"codec":"corporate-register-evidence-amendment-v1"}'
    elif attack == 'duplicate_nested': encoded = encoded.replace('"revision":1', '"revision":1,"revision":1', 1)
    elif attack == 'whitespace': encoded += '\n'
    elif attack == 'nan': encoded = encoded.replace('"revision":1','"revision":NaN',1)
    elif attack == 'wrong_codec': encoded = encoded.replace('amendment-v1','amendment-v2')
    elif attack == 'truncated': encoded = encoded[:-1]
    else: encoded = '[]'
    with pytest.raises(ERROR): gov.parse_corporate_register_evidence_amendment(encoded)


@pytest.mark.parametrize('change', ['replayed','naive','different_recorded_at','facts','accounting_entry','actor_type'])
def test_anchor_invalid_or_tampered_original_does_not_pass_integrity(change):
    anchor, _, _, receipt = fixture()
    if change == 'replayed':
        with pytest.raises(ERROR): gov.anchor_supported_corporate_event_evidence(replace(anchor.original,replayed=True), original_actor_id=anchor.original_actor_id)
        return
    original = anchor.original
    if change == 'naive': original=replace(original,recorded_at=NOW.replace(tzinfo=None))
    elif change == 'facts': original=replace(original,event=replace(original.event,facts_sha256='0'*64))
    elif change == 'accounting_entry': original=replace(original,accounting_entry_id=gov.AccountingEntryReference(identifier(90)))
    altered=replace(anchor,original=original)
    if change == 'different_recorded_at': altered=replace(altered,original_recorded_at=NOW+timedelta(microseconds=1))
    if change == 'actor_type': altered=replace(altered,original_actor_id=identifier(91))
    with pytest.raises(ERROR): gov.assert_corporate_register_evidence_amendment_integrity(replace(receipt,anchor=altered))


@pytest.mark.parametrize('value', [None, True, {}, 'original'])
def test_anchor_factory_rejects_wrong_original_types(value):
    with pytest.raises(ERROR): gov.anchor_supported_corporate_event_evidence(value, original_actor_id=UserId(identifier(90)))


def test_original_unknown_document_kind_raises_the_owned_pure_error():
    anchor, _, _, receipt = fixture()
    facts = json.loads(gov.serialize_corporate_register_evidence_amendment(receipt))['amendment']['anchor']['original']['canonicalFacts']
    facts['documentFacts'][0]['evidence_kind'] = 'unknown'
    original = replace(anchor.original, event=replace(anchor.original.event, canonical_facts=facts, facts_sha256=digest(facts)))
    with pytest.raises(ERROR): gov.anchor_supported_corporate_event_evidence(original, original_actor_id=anchor.original_actor_id)


@pytest.mark.parametrize('changed', ['base_target', 'self_head', 'receipt_hash', 'anchor_hash', 'base_actor', 'stored_time'])
def test_standalone_receipt_integrity_rejects_changed_bindings(changed):
    anchor, cmd, _, first = fixture(); receipt = first
    if changed == 'base_target': receipt = replace(first,command=replace(cmd,withdrawal=replace(cmd.withdrawal,target=source(8))))
    elif changed == 'self_head':
        receipt=follow(first); receipt=replace(receipt,command=replace(receipt.command,expected_head=replace(first.head,amendment_id=receipt.amendment_id)))
    elif changed == 'receipt_hash': receipt=replace(first,amendment_sha256='0'*64)
    elif changed == 'anchor_hash': receipt=replace(first,anchor=replace(anchor,anchor_sha256='0'*64))
    elif changed == 'base_actor': receipt=replace(first,anchor=replace(anchor,original_actor_id=UserId(identifier(90))))
    elif changed == 'stored_time': receipt=replace(first,recorded_at=first.recorded_at+timedelta(microseconds=1))
    with pytest.raises(ERROR): gov.assert_corporate_register_evidence_amendment_integrity(receipt)
