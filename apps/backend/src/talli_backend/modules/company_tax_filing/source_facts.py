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
)

_VERSION = 'company-tax-source-v1'
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
        for flag in ('inventoryValid', 'quarantineClear', 'sourceRowsValid', 'legacyFencesValid', 'modeChecksValid', 'declaredExtentValid'):
            if proof.get(flag) is not True:
                reasons.append(flag + '_unproven')
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
        digest = _digest({'version': _VERSION, 'rows': rows, 'coverage': snapshot.coverage,
                          'completeEnumeration': snapshot.complete_enumeration})
        evidence = CompanyTaxSourceEvidence(query.company_id, query.income_year,
            f'company-tax:{query.company_id}:{int(query.income_year)}', _VERSION + ':' + digest, digest, snapshot.as_of)
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
            tuple(corrections), tuple(incidents), tuple(outcomes))
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise CompanyTaxError.unavailable() from None


def verify(query: CompanyTaxSourceQuery, evidence: CompanyTaxSourceEvidence, snapshot: CompanyTaxSourceSnapshot) -> bool:
    if evidence.company_id != query.company_id or evidence.income_year != query.income_year or evidence.evaluated_at.value > snapshot.as_of.value:
        return False
    current = project(query, snapshot)
    return (evidence.obligation == current.evidence.obligation and evidence.scope == current.evidence.scope
            and evidence.reference == current.evidence.reference and evidence.version == current.evidence.version
            and evidence.digest == current.evidence.digest and current.history_coverage.status == 'complete')
