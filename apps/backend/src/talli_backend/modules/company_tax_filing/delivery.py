"""Immutable Tax delivery inputs and submit-once operation policy.

Persistence authorizes and commits an intent before its operation can execute.
An uncertain intent is reconciled by reads; this policy never authorizes a
second mutation simply because a request or process did not return.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
import re

from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId


def _json(value):
    if is_dataclass(value):
        return {field.name: _json(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError('Tax source keys must be text.')
        return {key: _json(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(child) for child in value]
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError('Tax amounts must be finite.')
        return str(value)
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError('Tax evidence times require a timezone.')
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError('Unsupported Tax source value.')


def tax_delivery_digest(value: object) -> str:
    raw = json.dumps(_json(value), sort_keys=True, separators=(',', ':'),
                     ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('Tax evidence digest is invalid.')
    return value


def _reference(value, label, maximum=4000):
    if (type(value) is not str or not value.strip() or len(value) > maximum
            or any(ord(char) < 32 for char in value)):
        raise ValueError('Tax ' + label + ' is invalid.')
    return value


@dataclass(frozen=True, slots=True)
class TaxDeliverySource:
    """One complete, scope-checked application read of owning source contracts.

    The application reads all pages in one repeatable source snapshot. Before a
    consequential effect it must reread and verify current facts under the
    company guard. The three upstream digests bind the complete reads; this
    value alone neither proves persistence nor grants filing permission.
    """
    company_id: CompanyId
    income_year: IncomeYear
    organization_number: str
    annual_data: Mapping[str, object]
    ledger_entries: tuple[Mapping[str, object], ...]
    holding_actions: tuple[Mapping[str, object], ...]
    upstream_sha256: Mapping[str, str]

    def __post_init__(self):
        from .public import _freeze_return_fact
        if (type(self.company_id) is not CompanyId or type(self.income_year) is not IncomeYear
                or type(self.income_year.value) is not int):
            raise ValueError('Tax source scope is invalid.')
        if type(self.organization_number) is not str or re.fullmatch(r'[0-9]{9}', self.organization_number) is None:
            raise ValueError('Tax organization number is invalid.')
        if (not isinstance(self.annual_data, Mapping)
                or not isinstance(self.ledger_entries, (list, tuple))
                or not isinstance(self.holding_actions, (list, tuple))
                or set(self.upstream_sha256) != {'annual', 'ledger', 'investments'}):
            raise ValueError('Tax source enumeration is incomplete.')
        for digest in self.upstream_sha256.values():
            _digest(digest)
        for row in (self.annual_data, *self.ledger_entries, *self.holding_actions):
            if (not isinstance(row, Mapping) or row.get('company_id') != str(self.company_id)
                    or type(row.get('income_year')) is not int
                    or row['income_year'] != int(self.income_year)):
                raise ValueError('Tax source company/year mismatch.')
        for rows in (self.ledger_entries, self.holding_actions):
            identifiers = [row.get('id') for row in rows]
            if (any(type(value) is not str or not value for value in identifiers)
                    or len(set(identifiers)) != len(identifiers)):
                raise ValueError('Tax source contains missing or duplicate identities.')
        # Snapshot every admitted value into canonical primitives first. Merely
        # freezing mappings/sequences would retain a caller-owned dataclass.
        tax_delivery_digest((self.annual_data, self.ledger_entries, self.holding_actions))
        for name in ('annual_data', 'ledger_entries', 'holding_actions', 'upstream_sha256'):
            object.__setattr__(self, name, _freeze_return_fact(_json(getattr(self, name))))

    @property
    def source_sha256(self):
        return tax_delivery_digest(self)


@dataclass(frozen=True, slots=True)
class TaxDeliveryEnvelope:
    source: TaxDeliverySource
    current_document_reference: str
    tax_xml: str
    business_xml: str
    envelope_xml: str
    schema_sha256: str

    def __post_init__(self):
        if type(self.source) is not TaxDeliverySource:
            raise ValueError('Tax delivery source is invalid.')
        _reference(self.current_document_reference, 'current document reference')
        _digest(self.schema_sha256)
        for value in (self.tax_xml, self.business_xml, self.envelope_xml):
            if type(value) is not str or not value or len(value.encode('utf-8')) > 8 * 1024 * 1024:
                raise ValueError('Tax delivery XML is missing or too large.')

    @property
    def envelope_sha256(self):
        return hashlib.sha256(self.envelope_xml.encode('utf-8')).hexdigest()

    @property
    def review_sha256(self):
        return tax_delivery_digest(self)


@dataclass(frozen=True, slots=True)
class TaxSchemaValidation:
    """Local XSD/code-list proof for exact bytes; no provider authorization."""
    schema_sha256: str
    source_sha256: str
    review_sha256: str
    tax_xml_sha256: str
    business_xml_sha256: str
    envelope_xml_sha256: str

    def __post_init__(self):
        for field in fields(self):
            _digest(getattr(self, field.name))

    def verify(self, envelope: TaxDeliveryEnvelope) -> None:
        if (self.schema_sha256 != envelope.schema_sha256
                or self.source_sha256 != envelope.source.source_sha256
                or self.review_sha256 != envelope.review_sha256
                or self.tax_xml_sha256 != hashlib.sha256(envelope.tax_xml.encode('utf-8')).hexdigest()
                or self.business_xml_sha256 != hashlib.sha256(envelope.business_xml.encode('utf-8')).hexdigest()
                or self.envelope_xml_sha256 != envelope.envelope_sha256):
            raise ValueError('Tax validation does not match the current schema and exact documents.')


def prepare_tax_delivery(source: TaxDeliverySource, *, party_number: str,
                         current_document_reference: str, schema_sha256: str) -> TaxDeliveryEnvelope:
    from .public import (CompanyTaxEnvelopeInput, CompanyTaxReturnSource, CompanyTaxReturnCandidate,
                         _calculation_source, _prepare_company_tax_candidate, render_company_tax_envelope)
    from .calculation import build
    if int(source.income_year) != 2025:
        raise ValueError('Tax delivery requires the supported 2025 schema/code-list generation.')
    _reference(current_document_reference, 'current document reference')
    if type(party_number) is not str or re.fullmatch(r'[0-9]{1,19}', party_number) is None:
        raise ValueError('Tax party number is invalid.')
    answers = source.annual_data.get('answers')
    if not isinstance(answers, Mapping) or answers.get('company_tax_additional_attachments') != 'none':
        raise ValueError('Tax additional attachment requirement must be explicitly none.')
    for name in ('shareholder_loans', 'declared_owner_dividends', 'bought_or_sold_shares'):
        if type(answers.get(name)) is not bool:
            raise ValueError('Tax annual answers must be explicit booleans.')
    # Common readiness remains the Annual owner's decision, consumed by the
    # application before review/dispatch. This function prepares Tax documents;
    # their existence is not an authorization or common-readiness attestation.
    for name in ('completed_at', 'updated_at'):
        value = source.annual_data.get(name)
        if type(value) is not str or datetime.fromisoformat(value).utcoffset() is None:
            raise ValueError('Tax annual completion evidence is missing.')
    if type(source.annual_data.get('no_activity_confirmed')) is not bool:
        raise ValueError('Tax no-activity declaration is invalid.')
    if source.annual_data['no_activity_confirmed'] and (
            source.holding_actions or any(row.get('entry_type') != 'opening_balance' for row in source.ledger_entries)):
        raise ValueError('Tax no-activity declaration contradicts recorded activity.')
    calculation_source = CompanyTaxReturnSource(
        organization_number=source.organization_number, income_year=int(source.income_year),
        annual_data=source.annual_data, ledger_entries=source.ledger_entries,
        holding_actions=source.holding_actions, party_number=party_number,
    )
    candidate = CompanyTaxReturnCandidate(**build(_calculation_source(calculation_source),
        projection_version='company-tax-delivery-2025-v1'))
    documents = _prepare_company_tax_candidate(candidate).documents
    envelope = render_company_tax_envelope(CompanyTaxEnvelopeInput(
        documents=documents,
        organization_number=source.organization_number, income_year=int(source.income_year),
        created_by='Talli', current_document_reference=current_document_reference,
    ))
    return TaxDeliveryEnvelope(source, current_document_reference, documents.tax_return_xml,
                               documents.business_specification_xml, envelope, schema_sha256)


class TaxMutationKind(StrEnum):
    CREATE_INSTANCE = 'create_instance'
    UPLOAD_ENVELOPE = 'upload_envelope'
    START_VALIDATION = 'start_validation'
    PREPARE_CONFIRMATION = 'prepare_confirmation'


class TaxMutationDisposition(StrEnum):
    EXECUTE = 'execute'
    REPLAY = 'replay'
    RECONCILE = 'reconcile'


def _mutation_result(kind, result):
    from uuid import UUID
    expected = {
        TaxMutationKind.CREATE_INSTANCE: {'instanceId'},
        TaxMutationKind.UPLOAD_ENVELOPE: {'instanceId', 'dataId', 'envelopeSha256'},
        TaxMutationKind.START_VALIDATION: {'instanceId', 'jobId'},
        TaxMutationKind.PREPARE_CONFIRMATION: {'instanceId', 'processTask'},
    }[kind]
    if set(result) != expected:
        raise ValueError('Tax operation result has missing or unexpected fields.')
    instance = result['instanceId']
    if (type(instance) is not str or '/' not in instance
            or re.fullmatch(r'[0-9]{1,19}', instance.split('/')[0]) is None
            or str(UUID(instance.split('/', 1)[1])) != instance.split('/', 1)[1]):
        raise ValueError('Tax operation instance is invalid.')
    if kind is TaxMutationKind.UPLOAD_ENVELOPE:
        if type(result['dataId']) is not str or str(UUID(result['dataId'])) != result['dataId']:
            raise ValueError('Tax envelope data identity is invalid.')
        _digest(result['envelopeSha256'])
    if kind is TaxMutationKind.START_VALIDATION and (
            type(result['jobId']) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,255}', result['jobId']) is None):
        raise ValueError('Tax validation job identity is invalid.')
    if kind is TaxMutationKind.PREPARE_CONFIRMATION and result['processTask'] != 'confirmation':
        raise ValueError('Tax owner confirmation was not prepared.')


@dataclass(frozen=True, slots=True)
class TaxMutationIntent:
    filing_id: str
    company_id: CompanyId
    income_year: IncomeYear
    approved_by: ActorId
    approval_sha256: str
    kind: TaxMutationKind
    request_sha256: str

    def __post_init__(self):
        from uuid import UUID
        if type(self.filing_id) is not str or str(UUID(self.filing_id)) != self.filing_id:
            raise ValueError('Tax filing identifier is invalid.')
        if (type(self.company_id) is not CompanyId or type(self.income_year) is not IncomeYear
                or type(self.income_year.value) is not int or type(self.approved_by) is not ActorId
                or self.approved_by.kind is not ActorKind.USER or type(self.approved_by.subject) is not UserId):
            raise ValueError('Tax mutation scope or approving actor is invalid.')
        if type(self.kind) is not TaxMutationKind:
            raise ValueError('Tax mutation kind is invalid.')
        _digest(self.approval_sha256)
        _digest(self.request_sha256)

    @property
    def identity_sha256(self):
        return tax_delivery_digest(self)


@dataclass(frozen=True, slots=True)
class TaxMutationRecord:
    intent: TaxMutationIntent
    state: str
    result: Mapping[str, object] | None = None

    def __post_init__(self):
        from .public import _freeze_return_fact
        if type(self.intent) is not TaxMutationIntent or self.state not in ('uncertain', 'completed'):
            raise ValueError('Tax mutation record state is invalid.')
        if (self.state == 'completed') != isinstance(self.result, Mapping):
            raise ValueError('Tax mutation completion evidence is missing or premature.')
        if self.result is not None:
            _mutation_result(self.intent.kind, self.result)
            tax_delivery_digest(self.result)
            object.__setattr__(self, 'result', _freeze_return_fact(self.result))


def plan_tax_mutation(intent: TaxMutationIntent, existing: TaxMutationRecord | None) -> TaxMutationDisposition:
    """EXECUTE is valid only for an atomically committed *new* intent.

    Persistence must perform the uniqueness/CAS check before returning that
    disposition. No timeout, lease expiry, new actor or changed request can turn
    an uncertain existing record back into a mutation permission.
    """
    if existing is None:
        return TaxMutationDisposition.EXECUTE
    if existing.intent != intent:
        raise ValueError('Tax operation replay changed its immutable binding.')
    return TaxMutationDisposition.REPLAY if existing.state == 'completed' else TaxMutationDisposition.RECONCILE


def verify_tax_review(envelope: TaxDeliveryEnvelope, *, expected_review_sha256: str,
                      current_source: TaxDeliverySource, current_schema_sha256: str,
                      current_document_reference: str) -> None:
    if (_digest(expected_review_sha256) != envelope.review_sha256
            or envelope.source != current_source
            or _digest(current_schema_sha256) != envelope.schema_sha256
            or _reference(current_document_reference, 'current document reference') != envelope.current_document_reference):
        raise ValueError('Tax review is stale or belongs to another source.')
