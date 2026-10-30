"""Positive source-v2 history binds every retained draft without authority claims."""
from dataclasses import replace
from datetime import UTC,datetime,timedelta
from uuid import uuid4

import pytest

from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsError,StoredAnnualAccountsDeliveryDraft,project_annual_accounts_source,verify_annual_accounts_source,
)
from talli_backend.shared.kernel import Timestamp
from test_annual_accounts_delivery_source import ACTOR,COMPANY,prepare,read,source_inputs
from test_annual_accounts_source_facts import parse,source


@pytest.fixture(scope='module')
def draft():
    inputs,app,_=source_inputs()
    return prepare(read(inputs,app))


def delivery_snapshot(draft):
    raw=source(True);raw.update(companyId=str(COMPANY),incomeYear=2025)
    raw['coverage'].update(companyId=str(COMPANY),incomeYear=2025)
    for rows in raw['workspace'].values():
        for row in rows:row['company_id']=str(COMPANY)
    query,snapshot=parse(raw);query=replace(query,actor_id=ACTOR)
    now=Timestamp(datetime.now(UTC));stored=StoredAnnualAccountsDeliveryDraft(draft,Timestamp(now.value-timedelta(seconds=1)))
    proof=dict(snapshot.coverage)|{'contractVersion':'annual-accounts-source-v2','declaredExtentValid':False,
        'declaredDeliveryExtentValid':True,'declaredTables':sorted((*snapshot.coverage['familyCounts'],'delivery_drafts','delivery_events')),
        'deliveryArchiveTrackingValid':True,'deliveryImmutableValid':True,'deliveryKeysValid':True,'deliveryDraftCount':1,
        'deliveryDraftDigests':{draft.filing_id:draft.sha256},'deliveryEventCount':0}
    return query,replace(snapshot,as_of=now,coverage=proof,contract_version='annual-accounts-source-v2',delivery_drafts=(stored,))


def test_positive_history_binds_exact_prepared_drafts_without_manufacturing_submissions(draft):
    query,snapshot=delivery_snapshot(draft);facts=project_annual_accounts_source(query,snapshot)
    assert facts.history_coverage.status=='complete',facts.history_coverage.reasons
    assert facts.delivery_drafts[0].draft_sha256==draft.sha256 and facts.delivery_drafts[0].status=='prepared_only'
    assert facts.readiness_status=='blocked' and facts.hard_blocks==('annual_accounts_production_disabled',)
    assert facts.recorded_submissions==facts.production_attempts==facts.outcomes==()
    assert verify_annual_accounts_source(query,facts.evidence,snapshot)
    assert not verify_annual_accounts_source(query,facts.evidence,replace(snapshot,delivery_drafts=()))


@pytest.mark.parametrize('defect',['extent','legacy-extent','tables','tracking','immutable','keys','version','count','digest','events','event-type','omitted'])
def test_incomplete_or_unreadable_delivery_history_never_claims_complete(draft,defect):
    query,snapshot=delivery_snapshot(draft);proof=dict(snapshot.coverage)
    if defect=='extent':proof['declaredDeliveryExtentValid']=False
    elif defect=='legacy-extent':proof['declaredExtentValid']=True
    elif defect=='tables':proof['declaredTables']=proof['declaredTables'][:-1]
    elif defect=='tracking':proof['deliveryArchiveTrackingValid']=False
    elif defect=='immutable':proof['deliveryImmutableValid']=False
    elif defect=='keys':proof['deliveryKeysValid']=False
    elif defect=='version':proof['contractVersion']='future'
    elif defect=='count':proof['deliveryDraftCount']=True
    elif defect=='digest':proof['deliveryDraftDigests']={draft.filing_id:'a'*64}
    elif defect=='events':proof['deliveryEventCount']=1
    elif defect=='event-type':proof['deliveryEventCount']=False
    snapshot=replace(snapshot,coverage=proof,delivery_drafts=() if defect=='omitted' else snapshot.delivery_drafts)
    assert project_annual_accounts_source(query,snapshot).history_coverage.status=='incomplete'


@pytest.mark.parametrize('defect',['duplicate','future','version','legacy','foreign'])
def test_ambiguous_foreign_future_or_unversioned_drafts_are_unavailable(draft,defect):
    query,snapshot=delivery_snapshot(draft)
    if defect=='duplicate':snapshot=replace(snapshot,delivery_drafts=snapshot.delivery_drafts*2)
    elif defect=='future':snapshot=replace(snapshot,delivery_drafts=(replace(snapshot.delivery_drafts[0],
        recorded_at=Timestamp(snapshot.as_of.value+timedelta(seconds=1))),))
    elif defect=='version':snapshot=replace(snapshot,contract_version='future')
    elif defect=='legacy':snapshot=replace(snapshot,contract_version='annual-accounts-source-v1')
    else:
        from talli_backend.shared.kernel import CompanyId
        query=replace(query,company_id=CompanyId(str(uuid4())))
    with pytest.raises(AnnualAccountsError):project_annual_accounts_source(query,snapshot)
