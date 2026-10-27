"""Lossless, scoped Accounts company-year copy; it grants no runtime authority."""
from dataclasses import dataclass
from datetime import datetime
import base64
import hashlib
import json

from talli_backend.shared.kernel import Timestamp
from .delivery import _canonical, decode_annual_accounts_delivery_draft, StoredAnnualAccountsDeliveryDraft
from .delivery_corrections import decode_annual_accounts_delivery_record_v2, inspect_annual_accounts_delivery_history, CORRECTION_RECORDS
from .delivery_journal import StoredAnnualAccountsDeliveryEvent
from .delivery_events import AnnualAccountsDeliveryObservation
from .delivery_corrections import AnnualAccountsCorrectionParentObservation

CODEC = 'annual-accounts-company-year-archive-v1'
MAX_BYTES = 192 * 1024 * 1024
FAMILIES = ('previews', 'submissions', 'overrides', 'review_comments', 'permissions', 'test_evidence')


@dataclass(frozen=True, slots=True)
class AnnualAccountsCompanyArchive:
    company_id: str
    income_year: int
    canonical_json: str
    sha256: str
    source_sha256: str
    draft_count: int
    event_count: int
    original_count: int
    codec: str = CODEC


@dataclass(frozen=True, slots=True)
class AccountsDeliveryOriginal:
    key: str
    purpose: str
    source_filing_id: str
    sha256: str
    media_type: str
    body_base64: str


def annual_accounts_delivery_originals(stored, events):
    """One catalog for the workspace, company archive and independent restore."""
    draft = stored.draft
    def original(key, purpose, raw, media):
        return AccountsDeliveryOriginal(key, purpose, draft.filing_id, hashlib.sha256(raw).hexdigest(), media, base64.b64encode(raw).decode())
    source = _canonical(json.loads(draft.canonical_json)['draft']['source']).encode()
    if hashlib.sha256(source).hexdigest() != draft.source.sha256:
        raise ValueError('Accounts source original differs.')
    result = [original('draft:' + draft.sha256, 'prepared_draft', draft.canonical_json.encode(), 'application/json'),
        original('source:' + draft.source.sha256, 'prepared_source', source, 'application/json'),
        original('prepared_main:' + draft.inspection.main_form_sha256, 'prepared_main', draft.main_form_xml.encode(), 'application/xml'),
        original('prepared_accounts:' + draft.inspection.company_accounts_sha256, 'prepared_accounts', draft.company_accounts_xml.encode(), 'application/xml')]
    for row in events:
        result.append(original('event:' + row.record.sha256, 'operation_record', row.record.canonical_json.encode(), 'application/json'))
        if type(row.record) in (AnnualAccountsDeliveryObservation, AnnualAccountsCorrectionParentObservation) and row.record.original.body_base64 is not None:
            value = row.record.original
            result.append(original('original:' + row.record.sha256,
                ('parent_' if type(row.record) is AnnualAccountsCorrectionParentObservation else '') + value.purpose.value,
                value.raw_bytes, value.content_type or 'application/octet-stream'))
    return tuple(result)


def _validate(query, snapshot, schemas):
    from .public import AnnualAccountsError, project_annual_accounts_source
    from .workspace import validate_rows
    validate_rows(snapshot.rows)
    facts = project_annual_accounts_source(query, snapshot)
    # Retained originals remain available for an unresolved predecessor effect.
    # No extent, enumeration, tracking, scope or lineage failure is waived.
    if (snapshot.contract_version not in ('annual-accounts-source-v3', 'annual-accounts-source-v4')
            or facts.history_coverage.status == 'unavailable'
            or set(facts.history_coverage.reasons) - {'production_journal_unavailable'}
            or snapshot.contract_version != 'annual-accounts-source-v4' and any(type(row.record) in CORRECTION_RECORDS for row in snapshot.delivery_events)):
        raise AnnualAccountsError.unavailable()
    for stored in snapshot.delivery_drafts:
        draft = stored.draft
        inspection = schemas.validate_pair(draft.main_form_xml.encode(), draft.company_accounts_xml.encode(),
            organization_number=draft.source.organization_number, income_year=int(draft.source.income_year))
        if inspection != draft.inspection:
            raise ValueError('Accounts draft schema inspection differs.')
    if snapshot.delivery_drafts:
        inspect_annual_accounts_delivery_history(snapshot.delivery_drafts, snapshot.delivery_events, schemas=schemas,
            expected_event_digests=dict(snapshot.coverage['deliveryEventDigests']))
    elif snapshot.delivery_events:
        raise ValueError('Accounts archive has events without drafts.')
    return facts


def serialize_annual_accounts_company_archive(query, snapshot, *, schemas):
    from .public import AnnualAccountsError
    try:
        facts = _validate(query, snapshot, schemas)
        value = {'codec': CODEC, 'companyId': str(query.company_id), 'incomeYear': int(query.income_year),
            'contractVersion': snapshot.contract_version, 'asOf': snapshot.as_of.value.isoformat(),
            'sourceSha256': facts.evidence.digest, 'rows': {key: getattr(snapshot.rows, key) for key in FAMILIES},
            'coverage': snapshot.coverage,
            'drafts': [{'canonicalJson': row.draft.canonical_json, 'sha256': row.draft.sha256,
                'recordedAt': row.recorded_at.value.isoformat()} for row in snapshot.delivery_drafts],
            'events': [{'sequence': row.sequence, 'canonicalJson': row.record.canonical_json, 'sha256': row.record.sha256,
                'recordedAt': row.recorded_at.value.isoformat()} for row in snapshot.delivery_events]}
        raw = _canonical(value)
        if len(raw.encode()) > MAX_BYTES:
            raise ValueError('Accounts archive exceeds its bound.')
        return raw
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        raise AnnualAccountsError.unavailable() from None


def build_annual_accounts_company_archive(query, snapshot, *, schemas):
    raw = serialize_annual_accounts_company_archive(query, snapshot, schemas=schemas)
    return AnnualAccountsCompanyArchive(str(query.company_id), int(query.income_year), raw,
        hashlib.sha256(raw.encode()).hexdigest(), json.loads(raw)['sourceSha256'],
        len(snapshot.delivery_drafts), len(snapshot.delivery_events),
        sum(len(annual_accounts_delivery_originals(stored, tuple(row for row in snapshot.delivery_events
            if row.record.binding.filing_id == stored.draft.filing_id))) for stored in snapshot.delivery_drafts))


def parse_annual_accounts_company_archive(raw, *, query, expected_sha256, schemas):
    """Verify the original scope; company/user identities are never rewritten."""
    from .public import AnnualAccountsError, AnnualAccountsFilingRows, AnnualAccountsSourceSnapshot
    try:
        if type(raw) is not str or len(raw.encode()) > MAX_BYTES or hashlib.sha256(raw.encode()).hexdigest() != expected_sha256:
            raise ValueError('Accounts archive commitment differs.')
        value = json.loads(raw)
        if (type(value) is not dict or set(value) != {'codec','companyId','incomeYear','contractVersion','asOf','sourceSha256','rows','coverage','drafts','events'}
                or value['codec'] != CODEC or value['companyId'] != str(query.company_id)
                or type(value['incomeYear']) is not int or value['incomeYear'] != int(query.income_year)
                or type(value['rows']) is not dict or set(value['rows']) != set(FAMILIES)
                or type(value['drafts']) is not list or len(value['drafts']) > 64
                or type(value['events']) is not list or len(value['events']) > 10000
                or _canonical(value) != raw):
            raise ValueError('Accounts archive scope or codec differs.')
        def timestamp(value):
            return Timestamp(datetime.fromisoformat(value.replace('Z', '+00:00')))
        drafts = []
        for row in value['drafts']:
            if type(row) is not dict or set(row) != {'canonicalJson','sha256','recordedAt'}:
                raise ValueError('Accounts draft archive row differs.')
            drafts.append(StoredAnnualAccountsDeliveryDraft(decode_annual_accounts_delivery_draft(row['canonicalJson'], row['sha256']), timestamp(row['recordedAt'])))
        events = []
        for row in value['events']:
            if type(row) is not dict or set(row) != {'sequence','canonicalJson','sha256','recordedAt'}:
                raise ValueError('Accounts event archive row differs.')
            events.append(StoredAnnualAccountsDeliveryEvent(row['sequence'], decode_annual_accounts_delivery_record_v2(row['canonicalJson'], row['sha256']), timestamp(row['recordedAt'])))
        snapshot = AnnualAccountsSourceSnapshot(AnnualAccountsFilingRows(query.company_id, query.income_year, **value['rows']),
            value['coverage'], timestamp(value['asOf']), True, value['contractVersion'], tuple(drafts), tuple(events))
        facts = _validate(query, snapshot, schemas)
        if facts.evidence.digest != value['sourceSha256']:
            raise ValueError('Accounts archive source commitment differs.')
        return snapshot
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        raise AnnualAccountsError.unavailable() from None
