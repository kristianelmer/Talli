"""Full-year facts enumerate retained evidence without claiming live admission."""
from dataclasses import fields, replace
from datetime import timedelta
import hashlib
import json

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.modules.shareholder_register_filing.source_facts import build_source_facts,verify_source_evidence,_value,_FULL_YEAR_FAMILIES
from talli_backend.shared.kernel import Timestamp
from test_rf1086_source_facts import snapshot as legacy_snapshot
from test_rf1086_archive_history import history_archive
from test_rf1086_year_source import ACTOR,NOW


def snapshot(archive=None):
    archive=archive or history_archive()[0]
    legacy=legacy_snapshot();h=archive.source_history
    workspace=rf.Rf1086WorkspaceSnapshot(archive.company_id,archive.income_year,**{
        name:getattr(archive,name) for name in ('previews','simulations','review_comments','permissions','test_evidence',
            'approvals','production_submissions')},feedback_artifacts=tuple(rf.Rf1086FeedbackArtifactRecord(
                **{f.name:getattr(row,f.name) for f in fields(rf.Rf1086FeedbackArtifactRecord)}) for row in archive.feedback_artifacts))
    counts={'year_source_versions':len(h.year_sources),'year_source_heads':int(h.year_source_head is not None),
        'register_observations':len(h.register_observations),'source_previews':len(h.source_previews),
        'source_review_bridges':len(h.review_bridges),'source_approval_bindings':len(archive.source_approval_lineage),
        'source_submission_bindings':len(archive.source_submission_claims),'submission_heads':int(archive.submission_head is not None)}
    events=tuple(rf.Rf1086JournalEvent(row.id,row.submission_id,i,row.operation_name,row.operation_state,row.body_hash,
        row.idempotency_key,row.authority_reference,row.failure_class,row.safe_error_code,row.created_at,row.attempt,
        row.resulting_status,'a'*64) for i,row in enumerate(archive.production_events,1))
    return replace(legacy,workspace=workspace,inventory=replace(legacy.inventory,company_id=archive.company_id,income_year=archive.income_year),
        journal_events=events,opening_sources=(),opening_facts=(),full_year_archive=archive,full_year_family_counts=counts,as_of=Timestamp(NOW))


def query(value):return rf.Rf1086SourceQuery(value.workspace.company_id,value.workspace.income_year,ACTOR)


@pytest.mark.parametrize('approved',[False,True])
def test_complete_captured_and_corrected_history_has_versioned_evidence(approved):
    current=snapshot(history_archive(approved=approved)[0]);facts=build_source_facts(query(current),current)
    assert facts.history_coverage.status=='complete',facts.history_coverage.reasons
    assert facts.evidence.version.startswith('rf1086-source-v2:')
    assert facts.readiness_status=='unavailable'
    assert facts.hard_blocks==('rf1086_full_year_readiness_not_evaluated',)
    assert verify_source_evidence(rf.VerifyRf1086SourceEvidenceQuery(query(current),facts.evidence),current)
    assert verify_source_evidence(rf.VerifyRf1086SourceEvidenceQuery(query(current),facts.evidence),replace(current,as_of=Timestamp(NOW+timedelta(days=1))))


@pytest.mark.parametrize('family',sorted(_FULL_YEAR_FAMILIES))
def test_positive_counts_prevent_silent_omission_of_any_new_family(family):
    current=snapshot();counts=dict(current.full_year_family_counts);counts[family]+=1
    facts=build_source_facts(query(current),replace(current,full_year_family_counts=counts))
    assert facts.history_coverage.status=='incomplete'
    assert 'full_year_enumeration_incomplete' in facts.history_coverage.reasons


@pytest.mark.parametrize('change',['archive','head','capture','preview','approval','observation','counts','bool-count','workspace'])
def test_missing_inconsistent_or_truncated_history_never_certifies_complete_extent(change):
    current=snapshot();archive=current.full_year_archive;h=archive.source_history
    if change=='archive':current=replace(current,full_year_archive=None)
    elif change=='head':current=replace(current,full_year_archive=replace(archive,source_history=replace(h,year_source_head=None)))
    elif change=='capture':current=replace(current,full_year_archive=replace(archive,source_history=replace(h,source_capture_records=())))
    elif change=='preview':current=replace(current,full_year_archive=replace(archive,source_history=replace(h,source_previews=())))
    elif change=='approval':current=replace(current,full_year_archive=replace(archive,source_approval_lineage=()))
    elif change=='observation':current=replace(current,full_year_archive=replace(archive,source_history=replace(h,register_observations=h.register_observations[1:])))
    elif change=='counts':current=replace(current,full_year_family_counts=None)
    elif change=='bool-count':current=replace(current,full_year_family_counts={**current.full_year_family_counts,'year_source_heads':True})
    elif change=='workspace':current=replace(current,workspace=replace(current.workspace,approvals=()))
    facts=build_source_facts(query(current),current)
    assert facts.history_coverage.status=='incomplete'
    assert not verify_source_evidence(rf.VerifyRf1086SourceEvidenceQuery(query(current),facts.evidence),current)


def test_v1_digest_is_byte_exact_and_cannot_verify_newly_enumerated_history():
    legacy=legacy_snapshot();facts=build_source_facts(query(legacy),legacy)
    payload=_value(legacy);payload.pop('as_of');payload.pop('full_year_archive');payload.pop('full_year_family_counts');payload['schema']='rf1086-source-v1'
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()
    assert facts.evidence.version=='rf1086-source-v1:'+digest
    assert facts.evidence.digest==digest
    empty=rf.Rf1086ArchiveSnapshot(legacy.workspace.company_id,legacy.workspace.income_year,
        previews=legacy.workspace.previews,permissions=legacy.workspace.permissions,source_history=rf.Rf1086ArchiveSourceHistory())
    current=replace(legacy,full_year_archive=empty,full_year_family_counts={key:0 for key in _FULL_YEAR_FAMILIES})
    assert build_source_facts(query(current),current).history_coverage.status=='complete'
    assert not verify_source_evidence(rf.VerifyRf1086SourceEvidenceQuery(query(legacy),facts.evidence),current)


def test_journal_and_feedback_projections_must_match_full_year_archive():
    from test_rf1086_source_submission_archive import source_submission_archive
    from test_rf1086_archive_history import with_captures
    archive=source_submission_archive('no_activity');line=archive.source_approval_lineage[0];source=line.source
    text=rf.serialize_rf1086_source_preview(line.source_preview)
    history=with_captures(rf.Rf1086ArchiveSourceHistory((source,),rf.Rf1086ArchiveYearSourceHead(source.company_id,
        source.income_year,source.source_id,source.version,source.source_sha256),source_previews=(
            rf.Rf1086ArchiveSourcePreview(line.source_preview,text,hashlib.sha256(text.encode()).hexdigest(),str(ACTOR.subject),NOW.isoformat()),),
        review_bridges=(line.bridge,)))
    current=snapshot(replace(archive,source_history=history));q=query(current)
    assert build_source_facts(q,current).history_coverage.status=='complete'
    for changed in (replace(current,journal_events=(replace(current.journal_events[0],state='unknown'),*current.journal_events[1:])),
                    replace(current,workspace=replace(current.workspace,feedback_artifacts=()))):
        assert build_source_facts(q,changed).history_coverage.status=='incomplete'


def test_new_unapproved_capture_invalidates_prior_full_year_evidence():
    current=snapshot(history_archive(approved=False)[0]);q=query(current);facts=build_source_facts(q,current)
    archive=current.full_year_archive;h=archive.source_history
    capture=replace(h.source_capture_records[-1],idempotency_key='changed-capture-key')
    updated=replace(current,full_year_archive=replace(archive,source_history=replace(h,
        source_capture_records=(*h.source_capture_records[:-1],capture))))
    assert build_source_facts(q,updated).history_coverage.status=='complete'
    assert not verify_source_evidence(rf.VerifyRf1086SourceEvidenceQuery(q,facts.evidence),updated)


def test_source_snapshot_reads_archive_and_independent_counts_on_one_repeatable_connection():
    import asyncio
    from contextlib import asynccontextmanager
    from test_postgres_shareholder_register_filing import session
    current=snapshot();store=session({});q=rf.Rf1086SourceQuery(current.workspace.company_id,current.workspace.income_year,store.actor_id)
    calls=[];transactions=[]
    class Connection:
        async def execute(self,sql,params):
            calls.append((sql,params));self.sql=sql
            assert params==(str(q.company_id),int(q.income_year)) or params==(str(q.company_id),)
            return self
        async def fetchone(self):
            if 'read_migration_inventory' in self.sql:return {'inventory':None}
            if 'transaction_timestamp' in self.sql:return {'observed_at':NOW,'complete':True}
            if 'count(*)' in self.sql:
                table=self.sql.split('shareholder_register_filing.')[1].split()[0]
                assert 'where company_id=%s::uuid and income_year=%s' in self.sql
                return {'count':current.full_year_family_counts[table]}
            raise AssertionError(self.sql)
        async def fetchall(self):return []
    connection=Connection()
    @asynccontextmanager
    async def transaction(*,snapshot):
        assert snapshot is True;transactions.append(connection);yield connection
    async def workspace(conn,query):
        assert conn is connection and query.company_id==q.company_id and query.income_year==q.income_year
        return current.workspace
    async def archive(conn,query,*,include_production):
        assert conn is connection and query.actor_id==q.actor_id and include_production is True
        return current.full_year_archive
    store._transaction=transaction;store._workspace=workspace;store._archive_source_on_connection=archive
    result=asyncio.run(store.source_snapshot(q))
    assert transactions==[connection]
    assert result.full_year_archive==current.full_year_archive and result.full_year_family_counts==current.full_year_family_counts
    assert sum('count(*)' in sql for sql,_ in calls)==8
