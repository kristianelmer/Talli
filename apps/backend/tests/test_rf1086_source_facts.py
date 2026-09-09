from __future__ import annotations
from dataclasses import replace,fields
from datetime import datetime,timedelta,timezone
import pytest
from talli_backend.modules.shareholder_register_filing.public import (
    Rf1086SourceQuery,Rf1086WorkspaceSnapshot,Rf1086OpeningBasis,OpeningSnapshotId,
    Rf1086SourceSnapshot,Rf1086OpeningSource,Rf1086MigrationInventory,VerifyRf1086SourceEvidenceQuery,
    Rf1086ProductionSubmissionRecord,Rf1086JournalEvent,Rf1086FeedbackArtifactRecord,
    Rf1086OverrideRecord,Rf1086ReviewCommentRecord,ShareholderRegisterFilingError,
    parse_rf1086_case,
)
from talli_backend.modules.shareholder_register_filing.source_facts import build_source_facts,verify_source_evidence,_REQUIRED_FAMILIES
from talli_backend.shared.kernel import Timestamp,CompanyId,IncomeYear
from test_rf1086_preparation import COMPANY,YEAR,ACTOR,CASES,preview,NOW

QUERY=Rf1086SourceQuery(COMPANY,YEAR,ACTOR)
NOW_TS=Timestamp(datetime.fromisoformat(NOW.replace('Z','+00:00')))

def snapshot():
    opening=Rf1086OpeningBasis(COMPANY,OpeningSnapshotId('40000000-0000-4000-8000-000000000004'),YEAR,parse_rf1086_case(CASES[0]['input']),'a'*64)
    workspace=Rf1086WorkspaceSnapshot(COMPANY,YEAR,previews=(preview(),))
    inventory=Rf1086MigrationInventory('migration-151:'+str(COMPANY)+':2025','rf151-v1','b'*64,COMPANY,YEAR,
        {name:0 for name in _REQUIRED_FAMILIES},{name:'c'*64 for name in _REQUIRED_FAMILIES},0,True)
    return Rf1086SourceSnapshot(workspace,inventory,(),(opening,),NOW_TS,True,
        (Rf1086OpeningSource(COMPANY,opening.opening_snapshot_id,YEAR,opening.source_digest,len(opening.case.shareholders)),))

def submission(id='50000000-0000-4000-8000-000000000005',*,status='approved',supersedes=None):
    return Rf1086ProductionSubmissionRecord(id,'60000000-0000-4000-8000-000000000006','70000000-0000-4000-8000-000000000007',
        str(COMPANY),str(ACTOR.subject),2025,'aksjonaerregisteroppgaven','rf1086_no_activity_v1','d'*64,
        'rf1086-production-v1','production',status,{},None,supersedes,str(ACTOR.subject),'unknown',0,None,None,None,None,NOW,NOW)

def event(*,state='unknown',operation='post_hovedskjema',reference=None,failure='unknown',submission_id=None):
    return Rf1086JournalEvent('80000000-0000-4000-8000-000000000008',submission_id or submission().id,1,operation,state,
        'd'*64,'90000000-0000-4000-8000-000000000009',reference,failure,'RF1086_OPERATION_ERROR' if failure else None,NOW,1,'unknown','e'*64)

def with_attempt(snap,record=None,events=()):
    return replace(snap,workspace=replace(snap.workspace,production_submissions=(record or submission(),)),journal_events=events)

def test_empty_history_requires_positive_attested_current_extent():
    facts=build_source_facts(QUERY,snapshot())
    assert facts.history_coverage.status=='complete'
    assert facts.history_coverage.scope=='talli_recorded_rf1086'
    assert facts.production_attempts==()
    assert facts.readiness_status=='ready'
    assert facts.evidence.obligation=='aksjonaerregisteroppgaven'
    assert not hasattr(facts,'production_submission_at')

@pytest.mark.parametrize('change,reason',[
    ({'inventory':None},'migration_coverage_missing'),
    ({'complete_enumeration':False},'journal_enumeration_incomplete'),
    ({'opening_facts':()},None),
])
def test_missing_proof_cannot_announce_absence(change,reason):
    facts=build_source_facts(QUERY,replace(snapshot(),**change))
    if reason:assert reason in facts.history_coverage.reasons and facts.history_coverage.status!='complete'
    else:assert facts.readiness_status=='unavailable'

@pytest.mark.parametrize('change,reason',[
    ({'reconciled':False},'migration_not_reconciled'),
    ({'quarantined_count':1},'migration_quarantine_unresolved'),
    ({'family_counts':{}},'migration_inventory_incomplete'),
    ({'family_digests':{}},'migration_inventory_incomplete'),
    ({'digest':'bad'},'migration_inventory_incomplete'),
    ({'income_year':IncomeYear(2024)},'migration_coverage_scope_mismatch'),
])
def test_partial_or_wrong_inventory_fails_closed(change,reason):
    original=snapshot();facts=build_source_facts(QUERY,replace(original,inventory=replace(original.inventory,**change)))
    assert facts.history_coverage.status=='incomplete'
    assert reason in facts.history_coverage.reasons


def test_truncated_history_rejected_even_if_adapter_marks_enumeration_complete():
    original=snapshot();counts=dict(original.inventory.family_counts);counts['production_filing_submissions']=1
    facts=build_source_facts(QUERY,replace(original,inventory=replace(original.inventory,family_counts=counts)))
    assert 'attested_history_not_fully_enumerated' in facts.history_coverage.reasons
    assert facts.history_coverage.status=='incomplete'

@pytest.mark.parametrize('state',['prepared','unknown'])
def test_ambiguous_mutation_is_not_absence_or_rejection(state):
    facts=build_source_facts(QUERY,with_attempt(snapshot(),events=(event(state=state),)))
    attempt=facts.production_attempts[0]
    assert attempt.effect_status=='unknown'
    assert attempt.observed_at is None
    if state=='unknown':assert facts.incidents[0].attribution=='unknown'


def test_read_success_is_not_proof_of_mutation():
    facts=build_source_facts(QUERY,with_attempt(snapshot(),events=(event(state='succeeded',operation='list_documents',reference='[]',failure=None),)))
    assert facts.production_attempts[0].effect_status=='not_observed'


def test_success_keeps_original_journal_observation_not_created_submission_time():
    record=replace(submission(status='received'),created_at='2020-01-01T00:00:00Z')
    facts=build_source_facts(QUERY,with_attempt(snapshot(),record,(event(state='succeeded',reference='main-id',failure=None),)))
    assert facts.production_attempts[0].effect_status=='confirmed'
    assert facts.production_attempts[0].observed_at==NOW
    assert facts.production_attempts[0].observed_at!=record.created_at


def test_superseded_attempt_remains_and_missing_parent_is_incomplete():
    original=snapshot();first=submission();second=submission('50000000-0000-4000-8000-000000000006',supersedes=first.id)
    snap=replace(original,workspace=replace(original.workspace,production_submissions=(second,first)))
    facts=build_source_facts(QUERY,snap)
    assert len(facts.production_attempts)==2 and facts.correction_links[0].supersedes_submission_id==first.id
    missing=build_source_facts(QUERY,replace(snap,workspace=replace(snap.workspace,production_submissions=(second,))))
    assert missing.history_coverage.status=='incomplete' and 'correction_history_missing' in missing.history_coverage.reasons


def test_evidence_verifier_checks_current_facts_not_only_age():
    original=snapshot();facts=build_source_facts(QUERY,original);query=VerifyRf1086SourceEvidenceQuery(QUERY,facts.evidence)
    assert verify_source_evidence(query,replace(original,as_of=Timestamp(NOW_TS.value+timedelta(days=1))))
    changed=replace(original,workspace=replace(original.workspace,previews=(replace(preview(),status='blocked'),)))
    assert not verify_source_evidence(query,changed)
    assert not verify_source_evidence(replace(query,evidence=replace(facts.evidence,digest='0'*64)),original)
    assert not verify_source_evidence(replace(query,evidence=replace(facts.evidence,reference='invented')),original)
    assert not verify_source_evidence(replace(query,evidence=replace(facts.evidence,evaluated_at=Timestamp(NOW_TS.value+timedelta(seconds=1)))),original)


def test_any_new_unknown_attempt_invalidates_previously_empty_history():
    original=snapshot();facts=build_source_facts(QUERY,original)
    assert not verify_source_evidence(VerifyRf1086SourceEvidenceQuery(QUERY,facts.evidence),with_attempt(original,events=(event(),)))


def test_opening_change_invalidates_ready_preview_and_evidence():
    original=snapshot();facts=build_source_facts(QUERY,original)
    basis=original.opening_facts[0]
    changed_case=replace(basis.case,company=replace(basis.case.company,name='Endret AS'))
    changed=replace(original,opening_facts=(replace(basis,case=changed_case),))
    result=build_source_facts(QUERY,changed)
    assert result.readiness_status=='blocked' and 'rf1086_preview_source_changed' in result.hard_blocks
    assert not verify_source_evidence(VerifyRf1086SourceEvidenceQuery(QUERY,facts.evidence),changed)

@pytest.mark.parametrize('kind',['comment','override'])
def test_rf_owned_hard_blocks_invalidate_source_readiness(kind):
    original=snapshot()
    if kind=='comment':
        comment=Rf1086ReviewCommentRecord('comment',preview().id,str(COMPANY),'rf1086_preview','hard_block','block',str(ACTOR.subject),None,None,NOW)
        workspace=replace(original.workspace,review_comments=(comment,))
    else:
        override=Rf1086OverrideRecord('override',preview().id,str(COMPANY),2025,preview().filing,'rf1086.x','0','1','block','block',str(ACTOR.subject),NOW,str(ACTOR.subject),NOW)
        workspace=replace(original.workspace,overrides=(override,))
    result=build_source_facts(QUERY,replace(original,workspace=workspace))
    assert result.readiness_status=='blocked'

@pytest.mark.parametrize('field,value',[('income_year',IncomeYear(2024)),('company_id',CompanyId('10000000-0000-4000-8000-000000000002'))])
def test_cross_scope_snapshot_is_never_published(field,value):
    original=snapshot()
    with pytest.raises(ShareholderRegisterFilingError):build_source_facts(QUERY,replace(original,workspace=replace(original.workspace,**{field:value})))


def test_source_values_are_recursively_immutable_and_detached():
    original=snapshot();counts=dict(original.inventory.family_counts)
    inventory=replace(original.inventory,family_counts=counts)
    counts['filing_previews']=99
    assert inventory.family_counts['filing_previews']==0
    with pytest.raises(TypeError):inventory.family_counts['filing_previews']=99
    facts=build_source_facts(QUERY,original)
    with pytest.raises((TypeError,AttributeError)):facts.hard_blocks+=('injected',)


def test_non_renderable_opening_preserves_attested_history_but_not_readiness():
    original=snapshot();counts=dict(original.inventory.family_counts)
    counts['opening_balance_setups']=1
    counts['opening_shareholders']=original.opening_sources[0].shareholder_count
    current=replace(original,inventory=replace(original.inventory,family_counts=counts),opening_facts=())
    facts=build_source_facts(QUERY,current)
    assert facts.history_coverage.status=='complete'
    assert facts.readiness_status=='unavailable'
    changed=replace(current,opening_sources=(replace(current.opening_sources[0],source_digest='f'*64),))
    assert not verify_source_evidence(VerifyRf1086SourceEvidenceQuery(QUERY,facts.evidence),changed)


def test_missing_raw_opening_cannot_be_substituted_with_a_renderable_case():
    facts=build_source_facts(QUERY,replace(snapshot(),opening_sources=()))
    assert facts.history_coverage.status=='incomplete'
    assert 'opening_source_enumeration_mismatch' in facts.history_coverage.reasons


@pytest.mark.parametrize('field,value',[('attempt',2),('resulting_status','action_required'),('source_digest','f'*64)])
def test_every_persisted_journal_attempt_fact_invalidates_source_evidence(field,value):
    original=with_attempt(snapshot(),events=(event(),))
    facts=build_source_facts(QUERY,original)
    changed=replace(original,journal_events=(replace(original.journal_events[0],**{field:value}),))
    assert not verify_source_evidence(VerifyRf1086SourceEvidenceQuery(QUERY,facts.evidence),changed)


def override(*,risk='advisory',id='override'):
    return Rf1086OverrideRecord(id,preview().id,str(COMPANY),2025,preview().filing,
        'rf1086.x','0','1','Owner-confirmed explanation',risk,str(ACTOR.subject),NOW,str(ACTOR.subject),NOW)


@pytest.mark.parametrize('risk',['advisory','warning'])
def test_non_block_override_preserves_acceptance_and_original_source_fact(risk):
    original=snapshot();record=override(risk=risk)
    current=replace(original,workspace=replace(original.workspace,overrides=(record,)))
    facts=build_source_facts(QUERY,current)
    assert facts.readiness_status=='ready'
    assert len(facts.warnings)==1
    warning=facts.warnings[0]
    assert (warning.code,warning.message,warning.source,warning.source_id)==(
        'accepted_filing_override',record.reason,'filing_overrides',record.id)
    assert (warning.risk_level,warning.accepted,warning.accepted_by,warning.accepted_at)==(
        risk,True,record.owner_confirmed_by,record.owner_confirmed_at)
    with pytest.raises((TypeError,AttributeError)):warning.accepted=False
    changed=replace(current,workspace=replace(current.workspace,overrides=(replace(record,owner_confirmed_at='2026-09-09T11:00:00Z'),)))
    assert not verify_source_evidence(VerifyRf1086SourceEvidenceQuery(QUERY,facts.evidence),changed)


def test_preview_warning_is_unaccepted_and_equal_override_reasons_keep_distinct_sources():
    from talli_backend.modules.shareholder_register_filing.public import Rf1086ReadinessIssue
    original=snapshot();p=replace(preview(),issues=(Rf1086ReadinessIssue('warning','synthetic_warning','Check the source'),))
    current=replace(original,workspace=replace(original.workspace,previews=(p,),overrides=(override(id='one'),override(id='two'))))
    facts=build_source_facts(QUERY,current)
    warning=facts.warnings[0]
    assert (warning.code,warning.message,warning.source,warning.source_id)==(
        'synthetic_warning','Check the source','filing_previews',p.id)
    assert (warning.risk_level,warning.accepted,warning.accepted_by,warning.accepted_at)==(None,False,None,None)
    assert [value.source_id for value in facts.warnings[1:]]==['one','two']


def test_block_override_does_not_become_accepted_warning():
    original=snapshot();current=replace(original,workspace=replace(original.workspace,overrides=(override(risk='block'),)))
    facts=build_source_facts(QUERY,current)
    assert facts.readiness_status=='blocked'
    assert facts.hard_blocks==('blocking_filing_override',)
    assert facts.warnings==()


@pytest.mark.parametrize('status',['accepted','rejected','action_required','received'])
def test_successful_reconciliation_keeps_outcome_discovery_separate_from_mutation(status):
    record=replace(submission(status=status),feedback_state='pending' if status=='received' else status,
        feedback_artifact_count=0 if status=='received' else 1)
    mutation=replace(event(state='succeeded',reference='main-id',failure=None),created_at='2026-09-09T11:00:00Z')
    reconciliation=replace(event(state='succeeded',operation='reconciliation:local-observation',failure=None),
        id='80000000-0000-4000-8000-000000000009',sequence=2,resulting_status=status)
    artifacts=() if status=='received' else (Rf1086FeedbackArtifactRecord(
        '40000000-0000-4000-8000-000000000001',str(COMPANY),record.id,
        '40000000-0000-4000-8000-000000000002','application/xml',100,'f'*64,NOW,status),)
    current=with_attempt(snapshot(),record,(mutation,reconciliation))
    current=replace(current,workspace=replace(current.workspace,feedback_artifacts=artifacts))
    facts=build_source_facts(QUERY,current)
    assert facts.history_coverage.status=='complete'
    assert facts.production_attempts[0].observed_at=='2026-09-09T11:00:00Z'
    assert facts.incidents==()
    assert len(facts.outcomes)==1
    outcome=facts.outcomes[0]
    assert (outcome.event_id,outcome.submission_id,outcome.resulting_status,outcome.observed_at)==(
        reconciliation.id,record.id,status,NOW)
    assert outcome.attribution=='unknown'
    with pytest.raises((TypeError,AttributeError)):outcome.resulting_status='invented'
    changed=replace(current,journal_events=(mutation,replace(reconciliation,created_at='2026-09-09T12:00:01Z')))
    assert not verify_source_evidence(VerifyRf1086SourceEvidenceQuery(QUERY,facts.evidence),changed)


def test_unknown_reconciliation_retains_incident_without_known_outcome():
    current=with_attempt(snapshot(),events=(event(operation='reconciliation:local-unknown'),))
    facts=build_source_facts(QUERY,current)
    assert len(facts.incidents)==1 and facts.incidents[0].observed_at==NOW
    assert facts.outcomes==()
