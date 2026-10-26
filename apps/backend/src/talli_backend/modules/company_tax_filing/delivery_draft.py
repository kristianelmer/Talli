"""Exact, versioned Tax draft bytes. A stored draft grants no filing authority."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
import hashlib
import json
from uuid import UUID

from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IdempotencyKey, IncomeYear, Timestamp, UserId
from .delivery import TaxDeliveryEnvelope, TaxDeliverySource, TaxSchemaValidation, _json
from .current_document import TaxCurrentDocument, _decode_current_document

if TYPE_CHECKING:
    from .delivery_correction import TaxDeliveryCorrectionParent

_VERSION = 'company-tax-delivery-draft-v1'
_CURRENT_VERSION = 'company-tax-delivery-draft-v2'
_CORRECTION_VERSION = 'company-tax-delivery-draft-v3'
_MAX_BYTES = 32 * 1024 * 1024


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _object(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('Tax draft shape is invalid.')
    return value


@dataclass(frozen=True, slots=True)
class TaxDeliveryDraft:
    filing_id: str
    command_key: IdempotencyKey
    prepared_by: ActorId
    envelope: TaxDeliveryEnvelope
    validation: TaxSchemaValidation
    current_document: TaxCurrentDocument | None = None
    correction_parent: TaxDeliveryCorrectionParent | None = None

    def __post_init__(self):
        if (type(self.filing_id) is not str or str(UUID(self.filing_id)) != self.filing_id
                or type(self.command_key) is not IdempotencyKey
                or type(self.prepared_by) is not ActorId or self.prepared_by.kind is not ActorKind.USER
                or type(self.prepared_by.subject) is not UserId
                or type(self.envelope) is not TaxDeliveryEnvelope
                or type(self.validation) is not TaxSchemaValidation):
            raise ValueError('Tax draft identity is invalid.')
        self.validation.verify(self.envelope)
        if self.current_document is not None:
            current = self.current_document
            if (type(current) is not TaxCurrentDocument
                    or current.response.organization_number != self.envelope.source.organization_number
                    or current.response.income_year != self.envelope.source.income_year
                    or current.document_reference != self.envelope.current_document_reference
                    or current.schema_sha256 != self.envelope.schema_sha256):
                raise ValueError('Current Tax original does not match the prepared delivery.')

        if self.correction_parent is not None:
            from .delivery_correction import TaxDeliveryCorrectionParent
            if type(self.correction_parent) is not TaxDeliveryCorrectionParent:
                raise ValueError('Tax correction parent type is invalid.')
            self.correction_parent.assert_child(self)

    @property
    def canonical_json(self) -> str:
        value = _json(self)
        value.pop('correction_parent')
        if self.correction_parent is not None:
            value['correction_parent']=self.correction_parent.canonical_value
        if self.current_document is None:
            value.pop('current_document')
        raw = _canonical({'version': _CORRECTION_VERSION if self.correction_parent is not None else _CURRENT_VERSION if self.current_document is not None else _VERSION, 'draft': value})
        if len(raw.encode('utf-8')) > _MAX_BYTES:
            raise ValueError('Tax draft exceeds the retained-byte limit.')
        return raw

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredTaxDeliveryDraft:
    draft: TaxDeliveryDraft
    recorded_at: Timestamp

    def __post_init__(self):
        if type(self.draft) is not TaxDeliveryDraft or type(self.recorded_at) is not Timestamp:
            raise ValueError('Retained Tax draft evidence is invalid.')


@dataclass(frozen=True, slots=True)
class TaxDeliveryDraftArchive:
    company_id: CompanyId
    income_year: IncomeYear
    drafts: tuple[StoredTaxDeliveryDraft, ...]
    source_sha256: str
    observed_at: Timestamp


def archive_tax_delivery_drafts(query, snapshot) -> TaxDeliveryDraftArchive:
    from .public import CompanyTaxError, project_company_tax_source
    facts = project_company_tax_source(query, snapshot)
    # Unknown effects on a retained legacy submission do not erase original
    # drafts. Every enumeration/migration/scope failure still blocks the export.
    if (snapshot.contract_version not in ('company-tax-source-v2','company-tax-source-v9')
            or facts.history_coverage.status == 'unavailable'
            or set(facts.history_coverage.reasons) - {'production_journal_unavailable'}):
        raise CompanyTaxError.unavailable()
    return TaxDeliveryDraftArchive(query.company_id, query.income_year,
        snapshot.delivery_drafts, facts.evidence.digest, snapshot.as_of)


def decode_tax_delivery_draft(raw: str, expected_sha256: str) -> TaxDeliveryDraft:
    """Reject lossy, ambiguous, altered or noncanonical persisted representations."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate Tax draft key.')
            result[key] = value
        return result

    def constant(_value):
        raise ValueError('Nonfinite Tax draft value.')

    try:
        if (type(raw) is not str or len(raw.encode('utf-8')) > _MAX_BYTES
                or hashlib.sha256(raw.encode('utf-8')).hexdigest() != expected_sha256):
            raise ValueError()
        root = _object(json.loads(raw, object_pairs_hook=pairs, parse_constant=constant), ('version', 'draft'))
        if root['version'] not in (_VERSION, _CURRENT_VERSION, _CORRECTION_VERSION):
            raise ValueError()
        current = root['version'] in (_CURRENT_VERSION,_CORRECTION_VERSION)
        correction = root['version'] == _CORRECTION_VERSION
        keys = ('filing_id', 'command_key', 'prepared_by', 'envelope', 'validation')
        value = _object(root['draft'], (*keys,'current_document','correction_parent') if correction else (*keys,'current_document') if current else keys)
        actor = _object(value['prepared_by'], ('kind', 'subject'))
        subject = _object(actor['subject'], ('value',))
        key = _object(value['command_key'], ('value',))
        envelope = _object(value['envelope'], ('source', 'current_document_reference', 'tax_xml',
            'business_xml', 'envelope_xml', 'schema_sha256'))
        source = _object(envelope['source'], ('company_id', 'income_year', 'organization_number',
            'annual_data', 'ledger_entries', 'holding_actions', 'upstream_sha256'))
        company = _object(source['company_id'], ('value',))
        year = _object(source['income_year'], ('value',))
        if type(year['value']) is not int or type(actor['kind']) is not str:
            raise ValueError()
        proof = _object(value['validation'], ('schema_sha256', 'source_sha256', 'review_sha256',
            'tax_xml_sha256', 'business_xml_sha256', 'envelope_xml_sha256'))
        source = TaxDeliverySource(**(source | {'company_id': CompanyId(company['value']),
            'income_year': IncomeYear(year['value'])}))
        from .delivery_correction import decode_tax_delivery_correction_parent
        draft = TaxDeliveryDraft(value['filing_id'], IdempotencyKey(key['value']),
            ActorId(ActorKind(actor['kind']), UserId(subject['value'])),
            TaxDeliveryEnvelope(**(envelope | {'source': source})), TaxSchemaValidation(**proof),
            _decode_current_document(value['current_document']) if current else None,
            decode_tax_delivery_correction_parent(value['correction_parent']) if correction else None)
        if draft.canonical_json != raw:
            raise ValueError()
        return draft
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError, OverflowError):
        raise ValueError('Retained Tax draft is invalid or its exact bytes changed.') from None
