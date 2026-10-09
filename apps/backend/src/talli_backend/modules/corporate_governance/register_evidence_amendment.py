"""Pure immutable evidence commitments, with no IO or live authority.

A valid supplied chain proves internal links only. It does not prove complete
storage, accepted ownership, fresh MFA, RF withdrawal/currentness, original-byte
retention, unchanged economics or Ledger eligibility. Those remain owner-backed
application/SQL obligations. No old Governance codec or digest is changed here.
"""
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import re
from uuid import UUID

from talli_backend.shared.kernel import (
    ActorId, ActorKind, CompanyId, IncomeYear, LocalDate, UserId,
)
from . import public as gov

_CODEC = 'corporate-register-evidence-amendment-v1'
_ANCHOR = 'corporate-supported-event-evidence-anchor-v1'
_REQUEST = 'corporate-register-evidence-amendment-request-v1'
_POLICY = 'corporate-governance-supported-events-2026.1'


def _require(condition, code):
    if not condition:
        raise gov.CorporateRegisterEvidenceAmendmentError('corporate_register_evidence_' + code)


def validate_identity(value):
    try:
        valid = type(value) is str and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        valid = False
    _require(valid, 'identity_invalid')


def _identity(value, cls):
    _require(type(value) is cls, 'identity_invalid')
    validate_identity(value.value)
    return value.value


def _sha(value):
    _require(type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None, 'digest_invalid')
    return value


def _integer(value, minimum=1, maximum=2147483647):
    _require(type(value) is int and minimum <= value <= maximum, 'integer_invalid')
    return value


def _text(value):
    _require(type(value) is str and '\x00' not in value, 'text_invalid')
    try:
        value.encode('utf-8', errors='strict')
    except UnicodeError:
        _require(False, 'text_invalid')
    return value


def _instant(value):
    _require(type(value) is datetime, 'time_invalid')
    try:
        _require(value.tzinfo is not None and value.utcoffset() is not None, 'time_invalid')
        return value.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise gov.CorporateRegisterEvidenceAmendmentError('corporate_register_evidence_time_invalid') from None


def _time(value):
    return _instant(value).isoformat(timespec='microseconds')


def _parse_time(value):
    _text(value)
    try:
        result = _instant(datetime.fromisoformat(value))
    except (ValueError, OverflowError):
        raise gov.CorporateRegisterEvidenceAmendmentError('corporate_register_evidence_time_invalid') from None
    _require(_time(result) == value, 'time_noncanonical')
    return result


def _year(value):
    _require(type(value) is IncomeYear, 'scope_invalid')
    return _integer(value.value, 2000, 2100)


def _plain(value):
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is str:
        return _text(value)
    if isinstance(value, Mapping):
        _require(all(type(key) is str for key in value), 'json_invalid')
        return {_text(key): _plain(item) for key, item in value.items()}
    if type(value) in (tuple, list):
        return [_plain(item) for item in value]
    _require(False, 'json_invalid')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return sha256(_json(value).encode('utf-8')).hexdigest()


def _fields(value, fields):
    _require(type(value) is dict and set(value) == set(fields.split()), 'shape_invalid')
    return value


def _source(value):
    _require(type(value) is gov.SupportedCorporateSourceFact, 'source_invalid')
    return {'record_id': _identity(value.record_id, gov.CorporateSourceReference),
            'revision': _integer(value.revision), 'fact_sha256': _sha(value.fact_sha256)}


def _parse_source(value):
    _fields(value, 'record_id revision fact_sha256')
    validate_identity(value['record_id']); _integer(value['revision']); _sha(value['fact_sha256'])
    return gov.SupportedCorporateSourceFact(gov.CorporateSourceReference(value['record_id']), value['revision'], value['fact_sha256'])


def _frozen_source(value):
    _fields(value, 'record_id revision fact_sha256'); _fields(value['record_id'], 'value')
    return _parse_source(dict(value, record_id=value['record_id']['value']))


def _document(value):
    _require(type(value) is gov.SupportedCorporateDocumentFact
             and type(value.evidence_kind) is gov.SupportedCorporateEvidenceKind, 'document_invalid')
    return {'document_id': _identity(value.document_id, gov.DocumentReference),
            'evidence_kind': value.evidence_kind.value, 'revision': _integer(value.revision),
            'content_sha256': _sha(value.content_sha256)}


def _parse_document(value):
    _fields(value, 'document_id evidence_kind revision content_sha256')
    validate_identity(value['document_id']); _integer(value['revision']); _sha(value['content_sha256'])
    _require(type(value['evidence_kind']) is str
             and value['evidence_kind'] in {kind.value for kind in gov.SupportedCorporateEvidenceKind}, 'document_invalid')
    return gov.SupportedCorporateDocumentFact(gov.DocumentReference(value['document_id']),
        gov.SupportedCorporateEvidenceKind(value['evidence_kind']), value['revision'], value['content_sha256'])


def _event_documents(original):
    values = _plain(original.event.canonical_facts)['documentFacts']
    _require(type(values) is list and 1 <= len(values) <= 12, 'document_invalid')
    result = []
    for value in values:
        _fields(value, 'document_id evidence_kind revision content_sha256')
        _fields(value['document_id'], 'value')
        result.append(_parse_document(dict(value, document_id=value['document_id']['value'])))
    return tuple(result)


def _original_payload(original):
    _require(type(original) is gov.RecordedSupportedCorporateEvent
             and type(original.event) is gov.CanonicalSupportedCorporateEvent, 'original_invalid')
    event = original.event
    _require(original.replayed is False and original.correction_of_event_id is None, 'original_invalid')
    _require((event.event_kind, event.phase) in (
        (gov.SupportedCorporateEventKind.CASH_CAPITAL_INCREASE, gov.SupportedCorporateEventPhase.REGISTERED),
        (gov.SupportedCorporateEventKind.LOSS_COVERAGE_CAPITAL_REDUCTION, gov.SupportedCorporateEventPhase.REGISTERED),
        (gov.SupportedCorporateEventKind.LOSS_COVERAGE_CAPITAL_REDUCTION, gov.SupportedCorporateEventPhase.FIRST_RECOGNIZED_AFTER_REGISTRATION)), 'event_ineligible')
    _require(type(event.event_kind) is gov.SupportedCorporateEventKind
             and type(event.phase) is gov.SupportedCorporateEventPhase, 'event_ineligible')
    _require(type(event.event_date) is LocalDate and type(event.event_date.value) is date, 'date_invalid')
    identity = {'eventId': _identity(event.event_id, gov.SupportedCorporateEventId),
        'eventReference': _identity(event.event_reference, gov.SupportedCorporateEventReference),
        'companyId': _identity(event.company_id, CompanyId), 'incomeYear': _year(event.income_year),
        'eventDate': event.event_date.value.isoformat(), 'eventKind': event.event_kind.value,
        'phase': event.phase.value, 'policyVersion': event.policy_version}
    _require(event.event_date.value.year == event.income_year.value and event.policy_version == _POLICY, 'scope_invalid')
    canonical = _plain(event.canonical_facts)
    _fields(canonical, 'eventId eventReference companyId incomeYear eventDate eventKind phase policyVersion businessFacts documentFacts bankFact shareholderRegisterFact taxCalculationFact')
    # JSON identity includes types: bool is not an income year, nor a revision.
    _integer(canonical['incomeYear'], 2000, 2100)
    _require(all(type(canonical[key]) is type(value) and canonical[key] == value for key, value in identity.items()), 'original_identity_mismatch')
    _require(_sha(event.facts_sha256) == _digest(canonical), 'original_facts_mismatch')
    _frozen_source(canonical['shareholderRegisterFact']); _event_documents(original)
    return dict(identity, canonicalFacts=canonical, factsSha256=event.facts_sha256,
        accountingEntryId=_identity(original.accounting_entry_id, gov.AccountingEntryReference),
        bankTransactionId=None if original.bank_transaction_id is None else _identity(original.bank_transaction_id, gov.BankTransactionReference),
        correctionOfEventId=None, recordedAt=_time(original.recorded_at), replayed=False,
        finalizationSha256=_sha(original.finalization_sha256))


def _anchor_body(anchor):
    _require(type(anchor) is gov.SupportedCorporateEventEvidenceAnchor, 'anchor_invalid')
    original = _original_payload(anchor.original)
    actor = _identity(anchor.original_actor_id, UserId)
    at = _time(anchor.original_recorded_at)
    _require(at == original['recordedAt'], 'original_time_mismatch')
    return {'original': original, 'original_actor_id': actor, 'original_recorded_at': at}


def _anchor_payload(anchor):
    body = _anchor_body(anchor)
    _require(_sha(anchor.anchor_sha256) == _digest([_ANCHOR, body]), 'anchor_integrity_mismatch')
    return dict(body, anchor_sha256=anchor.anchor_sha256)


def anchor_event(original, *, original_actor_id):
    _original_payload(original)
    anchor = gov.SupportedCorporateEventEvidenceAnchor(original, original_actor_id, _instant(original.recorded_at), '0' * 64)
    return replace(anchor, anchor_sha256=_digest([_ANCHOR, _anchor_body(anchor)]))


def _head(value):
    if value is None:
        return None
    _require(type(value) is gov.CorporateRegisterEvidenceAmendmentHead, 'head_invalid')
    return {'amendment_id': _identity(value.amendment_id, gov.CorporateRegisterEvidenceAmendmentId),
            'revision': _integer(value.revision), 'amendment_sha256': _sha(value.amendment_sha256)}


def _command_payload(command):
    _require(type(command) is gov.AmendSupportedCorporateRegisterEvidence, 'command_invalid')
    actor = command.actor_id
    _require(type(actor) is ActorId and actor.kind is ActorKind.USER and type(actor.kind) is ActorKind, 'actor_invalid')
    withdrawal = command.withdrawal
    _require(type(withdrawal) is gov.CorporateRegisterWithdrawalReference, 'withdrawal_invalid')
    reason = _text(command.reason)
    _require(bool(reason.strip()) and len(reason) <= 1000, 'reason_invalid')
    memo = _document(command.correction_memo)
    _require(command.correction_memo.evidence_kind is gov.SupportedCorporateEvidenceKind.CORRECTION_MEMO, 'memo_invalid')
    target, replacement = _source(withdrawal.target), _source(command.replacement)
    _require(target['record_id'] != replacement['record_id'], 'replacement_reused')
    return {'company_id': _identity(command.company_id, CompanyId), 'income_year': _year(command.income_year),
        'actor_id': {'kind': actor.kind.value, 'subject': _identity(actor.subject, UserId)},
        'event_id': _identity(command.event_id, gov.SupportedCorporateEventId),
        'expected_anchor_sha256': _sha(command.expected_anchor_sha256), 'expected_head': _head(command.expected_head),
        'withdrawal': {'withdrawal_id': _identity(withdrawal.withdrawal_id, gov.CorporateSourceReference),
            'withdrawal_sha256': _sha(withdrawal.withdrawal_sha256), 'target': target},
        'replacement': replacement, 'correction_memo': memo, 'reason': reason}


def request_digest(command):
    return _digest([_REQUEST, _command_payload(command)])


def _original_commitment(value):
    _require(type(value) is gov.CorporateDocumentOriginalCommitment, 'original_document_invalid')
    return {'original_id': _identity(value.original_id, gov.CorporateSourceReference),
        'document_id': _identity(value.document_id, gov.DocumentReference),
        'company_id': _identity(value.company_id, CompanyId), 'source_income_year': _year(value.source_income_year),
        'revision': _integer(value.revision), 'metadata_sha256': _sha(value.metadata_sha256),
        'content_sha256': _sha(value.content_sha256), 'byte_length': _integer(value.byte_length, 1, 10485760),
        'retained_at': _time(value.retained_at)}


def _receipt_body(receipt):
    _require(type(receipt) is gov.SupportedCorporateRegisterEvidenceAmendment, 'receipt_invalid')
    anchor, command = _anchor_payload(receipt.anchor), _command_payload(receipt.command)
    event = receipt.anchor.original.event
    _require((receipt.command.company_id, receipt.command.income_year, receipt.command.event_id,
              receipt.command.expected_anchor_sha256) ==
             (event.company_id, event.income_year, event.event_id, receipt.anchor.anchor_sha256), 'anchor_mismatch')
    revision = _integer(receipt.revision)
    expected = receipt.command.expected_head
    _require(revision == (1 if expected is None else expected.revision + 1), 'revision_mismatch')
    if expected is None:
        _require(receipt.command.withdrawal.target == _frozen_source(
            _plain(receipt.anchor.original.event.canonical_facts)['shareholderRegisterFact']), 'lineage_mismatch')
    else:
        _require(expected.amendment_id != receipt.amendment_id, 'lineage_mismatch')
    at = _instant(receipt.recorded_at)
    _require(at >= _instant(receipt.anchor.original_recorded_at), 'predates_original')
    _require(type(receipt.originals) is tuple, 'original_documents_invalid')
    originals = [_original_commitment(item) for item in receipt.originals]
    _require(originals == sorted(originals, key=lambda item: item['document_id']), 'original_documents_order')
    expected_documents = {(item.document_id.value, item.revision, item.content_sha256)
        for item in (*_event_documents(receipt.anchor.original), receipt.command.correction_memo)}
    actual_documents = {(item.document_id.value, item.revision, item.content_sha256) for item in receipt.originals}
    _require(len({item.document_id for item in receipt.originals}) == len(receipt.originals)
             and len({item.original_id for item in receipt.originals}) == len(receipt.originals)
             and expected_documents <= actual_documents, 'original_documents_mismatch')
    required_ids = {item[0] for item in expected_documents}
    for item in receipt.originals:
        _require(item.company_id == event.company_id
                 and (item.document_id.value not in required_ids or item.source_income_year == event.income_year)
                 and _instant(item.retained_at) <= at, 'original_documents_mismatch')
    _require(_sha(receipt.request_sha256) == request_digest(receipt.command), 'request_mismatch')
    return {'amendment_id': _identity(receipt.amendment_id, gov.CorporateRegisterEvidenceAmendmentId),
        'revision': revision, 'anchor': anchor, 'command': command, 'recorded_at': _time(at),
        'originals': originals, 'request_sha256': receipt.request_sha256}


def assert_integrity(receipt):
    body = _receipt_body(receipt)
    _require(_sha(receipt.amendment_sha256) == _digest([_CODEC, body]), 'integrity_mismatch')


def assert_replay(receipt, command):
    assert_integrity(receipt)
    _require(request_digest(command) == receipt.request_sha256 and command == receipt.command, 'replay_conflict')


def derive_chain(anchor, *, amendments):
    _anchor_payload(anchor)
    _require(type(amendments) is tuple, 'history_invalid')
    effective = _frozen_source(_plain(anchor.original.event.canonical_facts)['shareholderRegisterFact'])
    head, at = None, _instant(anchor.original_recorded_at)
    ids, withdrawals, used_targets = set(), set(), {effective.record_id}
    for row in amendments:
        assert_integrity(row)
        _require(_anchor_payload(row.anchor) == _anchor_payload(anchor), 'anchor_mismatch')
        command = row.command
        _require(command.expected_head == head and command.withdrawal.target == effective, 'lineage_mismatch')
        _require(row.amendment_id not in ids and command.withdrawal.withdrawal_id not in withdrawals,
                 'history_duplicate')
        _require(command.replacement.record_id not in used_targets, 'replacement_reused')
        _require(_instant(row.recorded_at) >= at if head is None else _instant(row.recorded_at) > at, 'lineage_time_invalid')
        ids.add(row.amendment_id); withdrawals.add(command.withdrawal.withdrawal_id)
        used_targets.add(command.replacement.record_id)
        effective, head, at = command.replacement, row.head, _instant(row.recorded_at)
    return gov.CorporateRegisterEvidenceChain(anchor, amendments, effective, head)


def prepare(command, *, anchor, amendment_id, recorded_at, originals, previous=()):
    chain = derive_chain(anchor, amendments=previous)
    _command_payload(command)
    _require(command.expected_head == chain.head and command.withdrawal.target == chain.effective_register_fact, 'lineage_mismatch')
    _require(type(originals) is tuple, 'original_documents_invalid')
    for item in originals:
        _original_commitment(item)
    originals = tuple(sorted((replace(item, retained_at=_instant(item.retained_at)) for item in originals), key=lambda item: item.document_id.value))
    receipt = gov.SupportedCorporateRegisterEvidenceAmendment(amendment_id, len(previous) + 1, anchor, command,
        _instant(recorded_at), originals, request_digest(command), '0' * 64)
    receipt = replace(receipt, amendment_sha256=_digest([_CODEC, _receipt_body(receipt)]))
    derive_chain(anchor, amendments=previous + (receipt,))
    return receipt


def serialize(receipt):
    assert_integrity(receipt)
    return _json({'codec': _CODEC, 'amendment': dict(_receipt_body(receipt), amendment_sha256=receipt.amendment_sha256)})


def _parse_original(value):
    _fields(value, 'eventId eventReference companyId incomeYear eventDate eventKind phase policyVersion canonicalFacts factsSha256 accountingEntryId bankTransactionId correctionOfEventId recordedAt replayed finalizationSha256')
    for key in ('eventId', 'eventReference', 'companyId', 'accountingEntryId'):
        validate_identity(value[key])
    _integer(value['incomeYear'], 2000, 2100); _sha(value['factsSha256']); _sha(value['finalizationSha256'])
    _require(value['correctionOfEventId'] is None and value['replayed'] is False, 'original_invalid')
    if value['bankTransactionId'] is not None:
        validate_identity(value['bankTransactionId'])
    day = date.fromisoformat(value['eventDate'])
    _require(day.isoformat() == value['eventDate'], 'date_invalid')
    _fields(value['canonicalFacts'], 'eventId eventReference companyId incomeYear eventDate eventKind phase policyVersion businessFacts documentFacts bankFact shareholderRegisterFact taxCalculationFact')
    original = gov.RecordedSupportedCorporateEvent(gov.CanonicalSupportedCorporateEvent(
        gov.SupportedCorporateEventId(value['eventId']), gov.SupportedCorporateEventReference(value['eventReference']),
        CompanyId(value['companyId']), IncomeYear(value['incomeYear']), LocalDate(day),
        gov.SupportedCorporateEventKind(value['eventKind']), gov.SupportedCorporateEventPhase(value['phase']),
        value['policyVersion'], value['canonicalFacts'], value['factsSha256']),
        gov.AccountingEntryReference(value['accountingEntryId']),
        None if value['bankTransactionId'] is None else gov.BankTransactionReference(value['bankTransactionId']),
        None, _parse_time(value['recordedAt']), False)
    _require(_original_payload(original) == value, 'original_integrity_mismatch')
    return original


def _parse_anchor(value):
    _fields(value, 'original original_actor_id original_recorded_at anchor_sha256')
    validate_identity(value['original_actor_id'])
    anchor = gov.SupportedCorporateEventEvidenceAnchor(_parse_original(value['original']), UserId(value['original_actor_id']),
        _parse_time(value['original_recorded_at']), value['anchor_sha256'])
    _anchor_payload(anchor)
    return anchor


def _parse_head(value):
    if value is None:
        return None
    _fields(value, 'amendment_id revision amendment_sha256')
    return gov.CorporateRegisterEvidenceAmendmentHead(gov.CorporateRegisterEvidenceAmendmentId(value['amendment_id']),
        _integer(value['revision']), _sha(value['amendment_sha256']))


def _parse_command(value):
    _fields(value, 'company_id income_year actor_id event_id expected_anchor_sha256 expected_head withdrawal replacement correction_memo reason')
    for key in ('company_id', 'event_id'):
        validate_identity(value[key])
    _integer(value['income_year'], 2000, 2100)
    actor = _fields(value['actor_id'], 'kind subject'); validate_identity(actor['subject'])
    withdrawal = _fields(value['withdrawal'], 'withdrawal_id withdrawal_sha256 target'); validate_identity(withdrawal['withdrawal_id'])
    command = gov.AmendSupportedCorporateRegisterEvidence(CompanyId(value['company_id']), IncomeYear(value['income_year']),
        ActorId(ActorKind(actor['kind']), UserId(actor['subject'])),
        gov.SupportedCorporateEventId(value['event_id']), value['expected_anchor_sha256'], _parse_head(value['expected_head']),
        gov.CorporateRegisterWithdrawalReference(gov.CorporateSourceReference(withdrawal['withdrawal_id']), withdrawal['withdrawal_sha256'], _parse_source(withdrawal['target'])),
        _parse_source(value['replacement']), _parse_document(value['correction_memo']), value['reason'])
    _command_payload(command)
    return command


def _parse_commitment(value):
    _fields(value, 'original_id document_id company_id source_income_year revision metadata_sha256 content_sha256 byte_length retained_at')
    for key in ('original_id', 'document_id', 'company_id'):
        validate_identity(value[key])
    _integer(value['source_income_year'], 2000, 2100)
    result = gov.CorporateDocumentOriginalCommitment(gov.CorporateSourceReference(value['original_id']),
        gov.DocumentReference(value['document_id']), CompanyId(value['company_id']), IncomeYear(value['source_income_year']),
        value['revision'], value['metadata_sha256'], value['content_sha256'], value['byte_length'], _parse_time(value['retained_at']))
    _original_commitment(result)
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'json_duplicate')
        result[key] = value
    return result


def parse(encoded):
    try:
        _text(encoded)
        value = json.loads(encoded, object_pairs_hook=_unique_object,
            parse_constant=lambda _: _require(False, 'json_invalid'))
        _fields(value, 'codec amendment'); _require(value['codec'] == _CODEC, 'codec_invalid')
        row = _fields(value['amendment'], 'amendment_id revision anchor command recorded_at originals request_sha256 amendment_sha256')
        _require(type(row['originals']) is list, 'original_documents_invalid')
        result = gov.SupportedCorporateRegisterEvidenceAmendment(gov.CorporateRegisterEvidenceAmendmentId(row['amendment_id']),
            row['revision'], _parse_anchor(row['anchor']), _parse_command(row['command']), _parse_time(row['recorded_at']),
            tuple(_parse_commitment(item) for item in row['originals']), row['request_sha256'], row['amendment_sha256'])
        assert_integrity(result)
        _require(serialize(result) == encoded, 'encoding_noncanonical')
        return result
    except gov.CorporateRegisterEvidenceAmendmentError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise gov.CorporateRegisterEvidenceAmendmentError('corporate_register_evidence_encoding_invalid') from None
