"""Evidence-bound Tax facts; no commercial decision or unobserved authority claim."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
import hashlib
import json
import re

from .public import (
    CompanyTaxError, CompanyTaxSourceQuery, CompanyTaxSourceSnapshot, CompanyTaxSourceEvidence,
    CompanyTaxHistoryCoverage, CompanyTaxSubmissionFact, CompanyTaxIncidentFact, CompanyTaxOutcomeFact,
    CompanyTaxCorrectionLink, CompanyTaxSourceFacts,
    StoredTaxDeliveryDraft, TaxDeliveryDraftFact,
    StoredTaxDeliveryEvent, TaxDeliveryJournal, TaxDeliveryJournalFact,
)
from .delivery_events import _guarded_upload_value,_validation_value,_confirmation_value

_VERSION = 'company-tax-source-v1'
_DELIVERY_VERSION = 'company-tax-source-v2'
_JOURNAL_VERSION = 'company-tax-source-v3'
_OBSERVATION_VERSION = 'company-tax-source-v4'
_GUARDED_UPLOAD_VERSION = 'company-tax-source-v5'
_VALIDATION_VERSION = 'company-tax-source-v6'
_CONFIRMATION_VERSION = 'company-tax-source-v7'
_DELIVERY_VERSIONS=(_DELIVERY_VERSION,_JOURNAL_VERSION,_OBSERVATION_VERSION,_GUARDED_UPLOAD_VERSION,_VALIDATION_VERSION,_CONFIRMATION_VERSION)
_JOURNAL_VERSIONS=(_JOURNAL_VERSION,_OBSERVATION_VERSION,_GUARDED_UPLOAD_VERSION,_VALIDATION_VERSION,_CONFIRMATION_VERSION)
_FAMILIES = {
    'filing_previews': 'previews', 'filing_submissions': 'submissions',
    'filing_overrides': 'overrides', 'filing_review_comments': 'review_comments',
    'authority_permissions': 'permissions', 'authority_test_runs': 'test_evidence',
}


def _value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_value(child) for child in value]
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(_value(value), sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _potential_production(row):
    # The predecessor permits adapter_mode=production even on simulation rows.
    # Such a label is neither a confirmed external effect nor proof of no effect.
    return (row.get('mode'), row.get('adapter_mode')) not in (
        ('simulation', 'simulation'), ('test_authority', 'test_authority'),
    )


def _coverage(query, snapshot, evidence_reference):
    proof = snapshot.coverage
    reasons = []
    if proof is None:
        reasons.append('migration_coverage_missing')
    else:
        if (proof.get('scope') != 'talli_recorded_company_tax' or proof.get('companyId') != str(query.company_id)
                or proof.get('incomeYear') != int(query.income_year)):
            reasons.append('migration_coverage_scope_mismatch')
        if proof.get('phase') not in ('cutover', 'contracted'):
            reasons.append('canonical_source_unavailable')
        if not re.fullmatch('[0-9a-f]{40}', str(proof.get('sourceRevision', ''))):
            reasons.append('migration_source_version_missing')
        extent_flag = ('declaredJournalExtentValid' if snapshot.contract_version in _JOURNAL_VERSIONS else
            'declaredDeliveryExtentValid' if snapshot.contract_version == _DELIVERY_VERSION else 'declaredExtentValid')
        for flag in ('inventoryValid', 'quarantineClear', 'sourceRowsValid', 'legacyFencesValid', 'modeChecksValid', extent_flag):
            if proof.get(flag) is not True:
                reasons.append(flag + '_unproven')
        if snapshot.contract_version in _DELIVERY_VERSIONS:
            if proof.get('deliveryDraftArchiveTrackingValid') is not True:
                reasons.append('delivery_archive_tracking_unproven')
            expected = sorted((*_FAMILIES, 'settlements', 'delivery_drafts',*(('delivery_events',) if snapshot.contract_version in _JOURNAL_VERSIONS else ())))
            if (proof.get('contractVersion') != snapshot.contract_version
                    or tuple(proof.get('declaredTables', ())) != tuple(expected)
                    or proof.get('declaredExtentValid') is not False):
                reasons.append('delivery_source_contract_unproven')
            drafts = snapshot.delivery_drafts
            if (type(proof.get('deliveryDraftCount')) is not int or proof['deliveryDraftCount'] != len(drafts)
                    or proof.get('deliveryDraftDigests') != {row.draft.filing_id: row.draft.sha256 for row in drafts}):
                reasons.append('delivery_draft_enumeration_incomplete')
        elif snapshot.delivery_drafts or proof.get('contractVersion') is not None:
            reasons.append('delivery_source_contract_required')
        if snapshot.contract_version in _JOURNAL_VERSIONS:
            events=snapshot.delivery_events
            if snapshot.contract_version in (_OBSERVATION_VERSION,_GUARDED_UPLOAD_VERSION,_VALIDATION_VERSION,_CONFIRMATION_VERSION):
                if proof.get('declaredObservationExtentValid') is not True or proof.get('observationCodecVersion')!='tax-read-evidence-v1':
                    reasons.append('observation_source_contract_unproven')
            if snapshot.contract_version in (_GUARDED_UPLOAD_VERSION,_VALIDATION_VERSION,_CONFIRMATION_VERSION):
                if proof.get('declaredGuardedUploadExtentValid') is not True or proof.get('guardedUploadCodecVersion')!='tax-guarded-upload-v1':
                    reasons.append('guarded_upload_source_contract_unproven')
            if snapshot.contract_version in (_VALIDATION_VERSION,_CONFIRMATION_VERSION):
                if proof.get('declaredValidationExtentValid') is not True or proof.get('validationCodecVersion')!='tax-validation-evidence-v1':
                    reasons.append('validation_source_contract_unproven')
            if snapshot.contract_version==_CONFIRMATION_VERSION:
                if proof.get('declaredConfirmationExtentValid') is not True or proof.get('confirmationCodecVersion')!='tax-confirmation-evidence-v1':
                    reasons.append('confirmation_source_contract_unproven')
            if proof.get('deliveryEventArchiveTrackingValid') is not True or proof.get('declaredDeliveryExtentValid') is not False:
                reasons.append('journal_archive_tracking_unproven')
            if (type(proof.get('deliveryEventCount')) is not int or proof['deliveryEventCount']!=len(events)
                    or proof.get('deliveryEventDigests')!={event.binding.filing_id+':'+event.slot:event.value.sha256 for event in events}):
                reasons.append('journal_enumeration_incomplete')
        elif snapshot.delivery_events:
            reasons.append('journal_source_contract_required')
        if set(proof.get('reconciledFamilies', ())) != set(_FAMILIES):
            reasons.append('migration_reconciliation_incomplete')
        counts, digests = proof.get('familyCounts'), proof.get('familyDigests')
        if (not isinstance(counts, Mapping) or set(counts) != set(_FAMILIES)
                or not isinstance(digests, Mapping) or set(digests) != set(_FAMILIES)):
            reasons.append('current_enumeration_incomplete')
        else:
            for family, field in _FAMILIES.items():
                if type(counts[family]) is not int or counts[family] != len(getattr(snapshot.rows, field)):
                    reasons.append('current_enumeration_count_mismatch')
                if not re.fullmatch('[0-9a-f]{64}', str(digests[family])):
                    reasons.append('current_enumeration_digest_missing')
        inventory = proof.get('inventory')
        if (not isinstance(inventory, Mapping)
                or not all('table:public.' + family in inventory for family in _FAMILIES)
                or any(not re.fullmatch('[0-9a-f]{64}', str(value)) for value in inventory.values())):
            reasons.append('migration_inventory_incomplete')
        retained = proof.get('retainedSubmissionIds')
        current_ids = {row['id'] for row in snapshot.rows.submissions}
        if (not isinstance(retained, (list, tuple)) or len(set(retained)) != len(retained)
                or not set(retained).issubset(current_ids)):
            reasons.append('retained_submission_history_missing')
    if snapshot.complete_enumeration is not True:
        reasons.append('source_enumeration_incomplete')
    if any(_potential_production(row) for row in snapshot.rows.submissions):
        reasons.append('production_journal_unavailable')
    ids = {row['id'] for row in snapshot.rows.submissions}
    if any(row.get('supersedes_submission_id') is not None and row['supersedes_submission_id'] not in ids
           for row in snapshot.rows.submissions):
        reasons.append('correction_history_missing')
    return CompanyTaxHistoryCoverage(
        'unavailable' if proof is None else 'incomplete' if reasons else 'complete',
        tuple(dict.fromkeys(reasons)), evidence_reference if proof is not None else None,
        snapshot.as_of, len(snapshot.rows.submissions),
    )


def project(query: CompanyTaxSourceQuery, snapshot: CompanyTaxSourceSnapshot) -> CompanyTaxSourceFacts:
    rows = snapshot.rows
    if rows.company_id != query.company_id or rows.income_year != query.income_year:
        raise CompanyTaxError.unavailable()
    try:
        if snapshot.contract_version not in (_VERSION, *_DELIVERY_VERSIONS):
            raise ValueError('Unsupported Tax source contract.')
        drafts = snapshot.delivery_drafts
        if (any(type(row) is not StoredTaxDeliveryDraft or row.draft.envelope.source.company_id != query.company_id
                or row.draft.envelope.source.income_year != query.income_year
                or row.recorded_at.value > snapshot.as_of.value for row in drafts)
                or len({row.draft.filing_id for row in drafts}) != len(drafts)):
            raise ValueError('Tax delivery history is incomplete or out of scope.')
        content = {'version': snapshot.contract_version, 'rows': rows, 'coverage': snapshot.coverage,
                   'completeEnumeration': snapshot.complete_enumeration}
        journals=[]
        if snapshot.contract_version in _DELIVERY_VERSIONS:
            # Bind exact versioned storage bytes, independent of future Python
            # dataclass fields or internal representations of the same original.
            content['deliveryDrafts'] = [{'filingId':row.draft.filing_id,
                'draftSha256':row.draft.sha256,'recordedAt':row.recorded_at.value.isoformat()} for row in drafts]
        if snapshot.contract_version in _JOURNAL_VERSIONS:
            events=snapshot.delivery_events;draft_ids={row.draft.filing_id for row in drafts}
            if snapshot.contract_version==_JOURNAL_VERSION and any(event.slot=='admission' or event.slot.startswith('observation:') for event in events):
                raise ValueError('Tax read evidence requires the positive V4 reader contract.')
            if snapshot.contract_version not in (_GUARDED_UPLOAD_VERSION,_VALIDATION_VERSION,_CONFIRMATION_VERSION) and any(_guarded_upload_value(event.value) for event in events):
                raise ValueError('Tax guarded upload originals require the positive V5 reader contract.')
            if snapshot.contract_version not in (_VALIDATION_VERSION,_CONFIRMATION_VERSION) and any(_validation_value(event.value) for event in events):
                raise ValueError('Tax validation originals require the positive V6 reader contract.')
            if snapshot.contract_version!=_CONFIRMATION_VERSION and any(_confirmation_value(event.value) for event in events):
                raise ValueError('Tax confirmation originals require the positive V7 reader contract.')
            if any(type(event) is not StoredTaxDeliveryEvent or event.binding.filing_id not in draft_ids
                    or event.recorded_at.value>snapshot.as_of.value for event in events):
                raise ValueError('Tax event history is incomplete or out of scope.')
            content['deliveryEvents']=[{'filingId':event.binding.filing_id,'slot':event.slot,
                'eventSha256':event.value.sha256,'recordedAt':event.recorded_at.value.isoformat(),
                'recordedBy':str(event.recorded_by.subject)} for event in events]
            for row in drafts:
                retained=tuple(event for event in events if event.binding.filing_id==row.draft.filing_id)
                journal=TaxDeliveryJournal(row.draft,retained,snapshot.contract_version in (_OBSERVATION_VERSION,_GUARDED_UPLOAD_VERSION,_VALIDATION_VERSION,_CONFIRMATION_VERSION),
                    snapshot.contract_version in (_GUARDED_UPLOAD_VERSION,_VALIDATION_VERSION,_CONFIRMATION_VERSION),snapshot.contract_version in (_VALIDATION_VERSION,_CONFIRMATION_VERSION),snapshot.contract_version==_CONFIRMATION_VERSION)
                if retained:
                    progress=journal.progress
                    journals.append(TaxDeliveryJournalFact(row.draft.filing_id,journal.approval.approved_by,
                        journal.approval.authority_mode,progress.status,progress.mutation_kind,journal.approval.sha256,
                        progress.latest_event_sha256,progress.recorded_at))
        digest = _digest(content)
        evidence = CompanyTaxSourceEvidence(query.company_id, query.income_year,
            f'company-tax:{query.company_id}:{int(query.income_year)}', snapshot.contract_version + ':' + digest, digest, snapshot.as_of)
        coverage = _coverage(query, snapshot, evidence.reference)
        submissions, attempts, incidents, outcomes, corrections = [], [], [], [], []
        for row in rows.submissions:
            row_digest = _digest(row)
            observed_at = row.get('updated_at') or row.get('created_at')
            potential = _potential_production(row)
            fact = CompanyTaxSubmissionFact(
                row['id'], row['mode'], row['adapter_mode'], row['status'],
                'unknown' if potential else 'not_production', observed_at,
                row.get('created_by'), row.get('submitted_by'), row.get('authority_confirmed_by'), row.get('authority_confirmed_at'),
                row.get('preview_confirmed_by'), row.get('preview_confirmed_at'), row.get('payload_hash'), row.get('receipt_id'),
                tuple(row.get('feedback_document_ids') or ()), row_digest,
            )
            submissions.append(fact)
            if potential:
                attempts.append(fact)
            if row.get('failure_code') or row['status'] in ('failed_retryable', 'failed_blocked'):
                incidents.append(CompanyTaxIncidentFact(row['id'], row['mode'], row['adapter_mode'],
                    row.get('failure_code'), observed_at, row.get('submitted_by') or row.get('created_by'), row_digest))
            # Row update time is a local observation, never the authority's event
            # time. Test feedback and terminal-looking states stay distinguished.
            outcome = 'unknown' if potential else 'test_or_simulation'
            outcomes.append(CompanyTaxOutcomeFact(row['id'], row['mode'], row['adapter_mode'], row['status'], outcome, observed_at, row_digest))
            if row.get('supersedes_submission_id'):
                corrections.append(CompanyTaxCorrectionLink(row['id'], row['supersedes_submission_id']))
        # The deployed Tax authority implementation currently refuses production.
        # This decisive source-owned gate cannot be enabled by a stored owner flag
        # or an imported test receipt. It certifies no other readiness prerequisite.
        status = 'unavailable' if coverage.status == 'unavailable' else 'blocked'
        blocks = ('company_tax_production_disabled',) if status == 'blocked' else ('company_tax_source_unavailable',)
        return CompanyTaxSourceFacts(evidence, status, blocks, coverage, tuple(submissions), tuple(attempts),
            tuple(corrections), tuple(incidents), tuple(outcomes), tuple(TaxDeliveryDraftFact(
                row.draft.filing_id, row.draft.prepared_by, row.recorded_at, row.draft.sha256,
                row.draft.envelope.review_sha256, row.draft.envelope.schema_sha256) for row in drafts),tuple(journals))
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise CompanyTaxError.unavailable() from None


def verify(query: CompanyTaxSourceQuery, evidence: CompanyTaxSourceEvidence, snapshot: CompanyTaxSourceSnapshot) -> bool:
    if evidence.company_id != query.company_id or evidence.income_year != query.income_year or evidence.evaluated_at.value > snapshot.as_of.value:
        return False
    current = project(query, snapshot)
    return (evidence.obligation == current.evidence.obligation and evidence.scope == current.evidence.scope
            and evidence.reference == current.evidence.reference and evidence.version == current.evidence.version
            and evidence.digest == current.evidence.digest and current.history_coverage.status == 'complete')
