"""Evidence-bound Accounts facts; no commercial decision or unobserved authority claim."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
import hashlib
import json
import re

from .public import (
    AnnualAccountsError, AnnualAccountsSourceQuery, AnnualAccountsSourceSnapshot, AnnualAccountsSourceEvidence,
    AnnualAccountsHistoryCoverage, AnnualAccountsSubmissionFact, AnnualAccountsIncidentFact, AnnualAccountsOutcomeFact,
    AnnualAccountsCorrectionLink, AnnualAccountsSourceFacts,
)

_VERSION = 'annual-accounts-source-v1'
_FAMILIES = {
    'filing_previews': 'previews', 'filing_submissions': 'submissions',
    'filing_overrides': 'overrides', 'filing_review_comments': 'review_comments',
    'authority_permissions': 'permissions', 'authority_test_runs': 'test_evidence',
}


def _digest(value):
    """Canonical JSON digest without a call-stack limit for opaque metadata."""
    digest = hashlib.sha256()
    active = set()
    pending = [('value', value)]
    while pending:
        operation, item = pending.pop()
        if operation == 'bytes':
            digest.update(item)
            continue
        if operation == 'close':
            container, closing = item
            active.remove(id(container))
            digest.update(closing)
            continue
        if isinstance(item, datetime):
            item = item.isoformat()
        if is_dataclass(item):
            item = {field.name: getattr(item, field.name) for field in fields(item)}
        if isinstance(item, (Mapping, list, tuple)):
            identity = id(item)
            if identity in active:
                raise ValueError('Cyclic source evidence')
            active.add(identity)
            mapping = isinstance(item, Mapping)
            entries = sorted(item.items()) if mapping else list(enumerate(item))
            digest.update(b'{' if mapping else b'[')
            pending.append(('close', (item, b'}' if mapping else b']')))
            for index in range(len(entries) - 1, -1, -1):
                key, child = entries[index]
                pending.append(('value', child))
                if mapping:
                    if not isinstance(key, str):
                        raise ValueError('Source JSON key must be text')
                    pending.append(('bytes', json.dumps(key, ensure_ascii=True).encode() + b':'))
                if index:
                    pending.append(('bytes', b','))
        else:
            digest.update(json.dumps(item, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode())
    return digest.hexdigest()


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
        if (proof.get('scope') != 'talli_recorded_annual_accounts' or proof.get('companyId') != str(query.company_id)
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
    return AnnualAccountsHistoryCoverage(
        'unavailable' if proof is None else 'incomplete' if reasons else 'complete',
        tuple(dict.fromkeys(reasons)), evidence_reference if proof is not None else None,
        snapshot.as_of, len(snapshot.rows.submissions),
    )


def project(query: AnnualAccountsSourceQuery, snapshot: AnnualAccountsSourceSnapshot) -> AnnualAccountsSourceFacts:
    rows = snapshot.rows
    if rows.company_id != query.company_id or rows.income_year != query.income_year:
        raise AnnualAccountsError.unavailable()
    try:
        digest = _digest({'version': _VERSION, 'rows': rows, 'coverage': snapshot.coverage,
                          'completeEnumeration': snapshot.complete_enumeration})
        evidence = AnnualAccountsSourceEvidence(query.company_id, query.income_year,
            f'annual-accounts:{query.company_id}:{int(query.income_year)}', _VERSION + ':' + digest, digest, snapshot.as_of)
        coverage = _coverage(query, snapshot, evidence.reference)
        submissions, attempts, incidents, outcomes, corrections = [], [], [], [], []
        for row in rows.submissions:
            row_digest = _digest(row)
            observed_at = row.get('updated_at') or row.get('created_at')
            potential = _potential_production(row)
            fact = AnnualAccountsSubmissionFact(
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
                incidents.append(AnnualAccountsIncidentFact(row['id'], row['mode'], row['adapter_mode'],
                    row.get('failure_code'), observed_at, row.get('submitted_by') or row.get('created_by'), row_digest))
            # Row update time is a local observation, never the authority's event
            # time. Test feedback and terminal-looking states stay distinguished.
            outcome = 'unknown' if potential else 'test_or_simulation'
            outcomes.append(AnnualAccountsOutcomeFact(row['id'], row['mode'], row['adapter_mode'], row['status'], outcome, observed_at, row_digest))
            if row.get('supersedes_submission_id'):
                corrections.append(AnnualAccountsCorrectionLink(row['id'], row['supersedes_submission_id']))
        # The deployed Accounts authority implementation currently refuses production.
        # This decisive source-owned gate cannot be enabled by a stored owner flag
        # or an imported test receipt. It certifies no other readiness prerequisite.
        status = 'unavailable' if coverage.status == 'unavailable' else 'blocked'
        blocks = ('annual_accounts_production_disabled',) if status == 'blocked' else ('annual_accounts_source_unavailable',)
        return AnnualAccountsSourceFacts(evidence, status, blocks, coverage, tuple(submissions), tuple(attempts),
            tuple(corrections), tuple(incidents), tuple(outcomes))
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise AnnualAccountsError.unavailable() from None


def verify(query: AnnualAccountsSourceQuery, evidence: AnnualAccountsSourceEvidence, snapshot: AnnualAccountsSourceSnapshot) -> bool:
    if evidence.company_id != query.company_id or evidence.income_year != query.income_year or evidence.evaluated_at.value > snapshot.as_of.value:
        return False
    current = project(query, snapshot)
    return (evidence.obligation == current.evidence.obligation and evidence.scope == current.evidence.scope
            and evidence.reference == current.evidence.reference and evidence.version == current.evidence.version
            and evidence.digest == current.evidence.digest and current.history_coverage.status == 'complete')
