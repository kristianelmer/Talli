"""Versioned evidence for RF-owned facts within the attested Talli journal extent."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
import hashlib
import json
import re

from .public import (
    Rf1086SourceQuery, Rf1086SourceSnapshot, Rf1086SourceEvidence,
    Rf1086SourceFacts, Rf1086HistoryCoverage, Rf1086ProductionAttemptFact,
    Rf1086CorrectionLink, Rf1086IncidentFact, Rf1086WarningFact, Rf1086OutcomeFact, VerifyRf1086SourceEvidenceQuery,
    ShareholderRegisterFilingError,
)
from .rendering import render_no_activity_rf1086_preview

_REQUIRED_FAMILIES = frozenset((
    'opening_balance_setups','opening_shareholders','filing_previews','filing_submissions',
    'filing_overrides','filing_review_comments','authority_permissions','authority_test_runs',
    'filing_approval_snapshots','production_filing_submissions','production_filing_events','production_feedback_artifacts',
))
_SCHEMA = 'rf1086-source-v1'


def _value(value):
    if isinstance(value, datetime): return value.isoformat()
    if is_dataclass(value): return {item.name:_value(getattr(value,item.name)) for item in fields(value)}
    if isinstance(value, Mapping): return {key:_value(child) for key,child in value.items()}
    if isinstance(value, (list,tuple)): return [_value(child) for child in value]
    return value


def _source_digest(snapshot: Rf1086SourceSnapshot) -> str:
    # A separately versioned evidence format: never changes historical payload
    # or production approval hashes. Read timestamps are not mutable facts.
    payload = _value(snapshot)
    payload.pop('as_of')
    payload['schema'] = _SCHEMA
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('utf-8')).hexdigest()


def _coverage(query: Rf1086SourceQuery, snapshot: Rf1086SourceSnapshot) -> Rf1086HistoryCoverage:
    inventory = snapshot.inventory
    reasons = []
    if inventory is None:
        reasons.append('migration_coverage_missing')
    elif (inventory.scope != 'talli_recorded_rf1086' or inventory.company_id != query.company_id
            or inventory.income_year != query.income_year):
        reasons.append('migration_coverage_scope_mismatch')
    else:
        if not inventory.reconciled: reasons.append('migration_not_reconciled')
        if inventory.quarantined_count != 0: reasons.append('migration_quarantine_unresolved')
        if (set(inventory.family_counts) != _REQUIRED_FAMILIES or set(inventory.family_digests) != _REQUIRED_FAMILIES
                or any(type(count) is not int or count < 0 for count in inventory.family_counts.values())
                or any(re.fullmatch('[0-9a-f]{64}',digest) is None for digest in inventory.family_digests.values())
                or not inventory.reference or not inventory.version or re.fullmatch('[0-9a-f]{64}',inventory.digest) is None):
            reasons.append('migration_inventory_incomplete')
    if snapshot.complete_enumeration is not True: reasons.append('journal_enumeration_incomplete')
    current_counts = {
        'opening_balance_setups':len(snapshot.opening_sources),
        'opening_shareholders':sum(source.shareholder_count for source in snapshot.opening_sources
            if type(source.shareholder_count) is int and source.shareholder_count >= 0),
        'filing_previews':len(snapshot.workspace.previews), 'filing_submissions':len(snapshot.workspace.simulations),
        'filing_overrides':len(snapshot.workspace.overrides), 'filing_review_comments':len(snapshot.workspace.review_comments),
        'authority_permissions':len(snapshot.workspace.permissions), 'authority_test_runs':len(snapshot.workspace.test_evidence),
        'filing_approval_snapshots':len(snapshot.workspace.approvals),
        'production_filing_submissions':len(snapshot.workspace.production_submissions),
        'production_filing_events':len(snapshot.journal_events),
        'production_feedback_artifacts':len(snapshot.workspace.feedback_artifacts),
    }
    if inventory is not None and any(current_counts.get(family,0) < count
            for family,count in inventory.family_counts.items() if type(count) is int):
        reasons.append('attested_history_not_fully_enumerated')
    sources = {source.opening_snapshot_id:source for source in snapshot.opening_sources}
    if len(sources) != len(snapshot.opening_sources): reasons.append('duplicate_opening_identity')
    if any(type(source.shareholder_count) is not int or source.shareholder_count < 0
            or re.fullmatch('[0-9a-f]{64}',source.source_digest) is None
            for source in snapshot.opening_sources):
        reasons.append('opening_source_enumeration_invalid')
    if any(basis.opening_snapshot_id not in sources
            or sources[basis.opening_snapshot_id].source_digest != basis.source_digest
            or sources[basis.opening_snapshot_id].shareholder_count != len(basis.case.shareholders)
            for basis in snapshot.opening_facts):
        reasons.append('opening_source_enumeration_mismatch')
    submissions = {row.id: row for row in snapshot.workspace.production_submissions}
    if len(submissions) != len(snapshot.workspace.production_submissions): reasons.append('duplicate_submission_identity')
    if any(re.fullmatch('[0-9a-f]{64}',event.source_digest) is None for event in snapshot.journal_events):
        reasons.append('journal_source_digest_invalid')
    event_ids = {event.id for event in snapshot.journal_events}
    if len(event_ids) != len(snapshot.journal_events): reasons.append('duplicate_event_identity')
    if any(event.submission_id not in submissions for event in snapshot.journal_events): reasons.append('journal_submission_link_missing')
    if any(row.supersedes_submission_id is not None and row.supersedes_submission_id not in submissions for row in submissions.values()):
        reasons.append('correction_history_missing')
    if any(artifact.submission_id not in submissions for artifact in snapshot.workspace.feedback_artifacts):
        reasons.append('artifact_submission_link_missing')
    status = 'unavailable' if inventory is None else 'incomplete' if reasons else 'complete'
    return Rf1086HistoryCoverage(status,inventory.reference if inventory else None,tuple(reasons),snapshot.as_of,
        len(snapshot.journal_events),max((event.sequence for event in snapshot.journal_events),default=None))


def _assert_scope(query: Rf1086SourceQuery, snapshot: Rf1086SourceSnapshot):
    from .preparation import validate_workspace
    from .public import Rf1086WorkspaceQuery
    workspace = validate_workspace(Rf1086WorkspaceQuery(query.company_id,query.actor_id,query.income_year),snapshot.workspace)
    if workspace.company_id != query.company_id or workspace.income_year != query.income_year:
        raise ShareholderRegisterFilingError.unavailable()
    for collection in (workspace.previews,workspace.simulations,workspace.overrides,workspace.approvals,workspace.production_submissions):
        if any(row.company_id != str(query.company_id) or row.income_year != query.income_year.value for row in collection):
            raise ShareholderRegisterFilingError.unavailable()
    for collection in (workspace.review_comments,workspace.permissions,workspace.test_evidence,workspace.feedback_artifacts):
        if any(row.company_id != str(query.company_id) for row in collection):
            raise ShareholderRegisterFilingError.unavailable()
    if any(basis.company_id != query.company_id or basis.income_year != query.income_year for basis in (*snapshot.opening_facts,*snapshot.opening_sources)):
        raise ShareholderRegisterFilingError.unavailable()


def _readiness(snapshot: Rf1086SourceSnapshot):
    workspace = snapshot.workspace
    hard_blocks = []; warnings = []
    preview = max(workspace.previews,key=lambda row:(row.created_at,row.id),default=None)
    if preview is None: return 'unavailable',('rf1086_preview_missing',),()
    if preview.status != 'ready': hard_blocks.append('rf1086_preview_not_ready')
    basis = next((item for item in snapshot.opening_facts if str(item.opening_snapshot_id) == preview.setup_id),None)
    if basis is None:
        return 'unavailable',('rf1086_opening_source_missing',),()
    current = render_no_activity_rf1086_preview(basis.case)
    if current.status != 'ready': hard_blocks.extend(issue.code for issue in current.issues if issue.level == 'error')
    if current.hovedskjema_xml != preview.hovedskjema_xml or current.underskjema_xml != preview.underskjema_xml:
        hard_blocks.append('rf1086_preview_source_changed')
    hard_blocks.extend(issue.code for issue in preview.issues if issue.level == 'error')
    warnings.extend(Rf1086WarningFact(issue.code,issue.message,'filing_previews',preview.id,None,False,None,None)
        for issue in preview.issues if issue.level == 'warning')
    if any(comment.preview_id == preview.id and comment.severity == 'hard_block' for comment in workspace.review_comments):
        hard_blocks.append('hard_review_block')
    if any(override.risk_level == 'block' for override in workspace.overrides): hard_blocks.append('blocking_filing_override')
    warnings.extend(Rf1086WarningFact('accepted_filing_override',override.reason,'filing_overrides',override.id,
        override.risk_level,True,override.owner_confirmed_by,override.owner_confirmed_at)
        for override in workspace.overrides if override.risk_level != 'block')
    return ('blocked' if hard_blocks else 'ready'),tuple(dict.fromkeys(hard_blocks)),tuple(warnings)


def build_source_facts(query: Rf1086SourceQuery, snapshot: Rf1086SourceSnapshot) -> Rf1086SourceFacts:
    _assert_scope(query,snapshot)
    digest = _source_digest(snapshot)
    evidence = Rf1086SourceEvidence(query.company_id,query.income_year,
        f'rf1086:{query.company_id}:{query.income_year.value}',_SCHEMA+':'+digest,digest,snapshot.as_of)
    coverage = _coverage(query,snapshot)
    readiness,blocks,warnings = _readiness(snapshot)
    attempts = []
    for row in snapshot.workspace.production_submissions:
        events = tuple(event for event in snapshot.journal_events if event.submission_id == row.id)
        mutations = tuple(event for event in events if event.operation_name in ('post_hovedskjema','confirm') or event.operation_name.startswith('post_underskjema:'))
        succeeded = tuple(event for event in mutations if event.state == 'succeeded' and event.authority_reference)
        uncertain = any(event.state in ('prepared','unknown') or event.failure_classification == 'unknown' for event in mutations)
        effect = 'confirmed' if succeeded else 'unknown' if uncertain or row.status not in ('approved',) else 'not_observed'
        # observed_at is a journal observation time, never asserted to be the
        # external authority's actual submission/receipt time.
        observed = min((event.created_at for event in succeeded),default=None)
        attempts.append(Rf1086ProductionAttemptFact(row.id,row.status,row.feedback_state,effect,observed,
            tuple(event.id for event in events),tuple(artifact.document_id for artifact in snapshot.workspace.feedback_artifacts if artifact.submission_id == row.id)))
    corrections = tuple(Rf1086CorrectionLink(row.id,row.supersedes_submission_id) for row in snapshot.workspace.production_submissions if row.supersedes_submission_id)
    incidents = tuple(Rf1086IncidentFact(event.id,event.submission_id,event.failure_classification,event.safe_error_code,event.created_at)
        for event in snapshot.journal_events if event.state in ('failed','unknown'))
    # A successful read can discover a negative authority result. Preserve that
    # observation independently of failed transport operations and mutation time.
    outcomes = tuple(Rf1086OutcomeFact(event.id,event.submission_id,event.resulting_status,event.created_at)
        for event in snapshot.journal_events if event.state == 'succeeded' and event.operation_name.startswith('reconciliation:'))
    return Rf1086SourceFacts(evidence,readiness,blocks,warnings,coverage,tuple(attempts),corrections,incidents,outcomes)


def verify_source_evidence(query: VerifyRf1086SourceEvidenceQuery, snapshot: Rf1086SourceSnapshot) -> bool:
    if query.evidence.company_id != query.query.company_id or query.evidence.income_year != query.query.income_year:
        return False
    if query.evidence.evaluated_at.value > snapshot.as_of.value:
        return False
    current = build_source_facts(query.query,snapshot)
    expected = current.evidence
    return (query.evidence.obligation == expected.obligation and query.evidence.reference == expected.reference
        and query.evidence.version == expected.version and query.evidence.digest == expected.digest
        and current.history_coverage.status == 'complete')
