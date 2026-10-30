"""Source v3 commits to all retained records without claiming provider authority."""
from dataclasses import replace

import pytest

from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsError,project_annual_accounts_source,verify_annual_accounts_source
from test_annual_accounts_delivery_records import draft
from test_annual_accounts_delivery_draft import delivery_snapshot
from test_annual_accounts_delivery_journal import complete_world


def event_source(draft):
    query,snapshot=delivery_snapshot(draft);world=complete_world(draft)
    proof=dict(snapshot.coverage)|{'contractVersion':'annual-accounts-source-v3',
        'deliveryEventCodecVersion':'annual-accounts-delivery-events-v1','deliveryEventContractValid':True,
        'deliveryEventCount':len(world.events),'deliveryEventDigests':world.expected}
    return query,replace(snapshot,contract_version='annual-accounts-source-v3',coverage=proof,
        delivery_drafts=(world.stored,),delivery_events=world.events)


def test_complete_source_commits_exact_full_journal_without_a_submission_claim(draft):
    query,snapshot=event_source(draft);facts=project_annual_accounts_source(query,snapshot)
    assert facts.history_coverage.status=='complete' and facts.recorded_submissions==facts.production_attempts==()
    assert facts.hard_blocks==('annual_accounts_production_disabled',)
    assert verify_annual_accounts_source(query,facts.evidence,snapshot)
    assert not verify_annual_accounts_source(query,facts.evidence,replace(snapshot,delivery_events=snapshot.delivery_events[:-1]))


@pytest.mark.parametrize('defect',['omitted','bool-count','digest','codec','contract'])
def test_missing_positive_event_commitment_is_incomplete(draft,defect):
    query,snapshot=event_source(draft);proof=dict(snapshot.coverage)
    if defect=='omitted':snapshot=replace(snapshot,delivery_events=snapshot.delivery_events[:-1])
    elif defect=='bool-count':proof['deliveryEventCount']=True
    elif defect=='digest':proof['deliveryEventDigests']={}
    elif defect=='codec':proof['deliveryEventCodecVersion']='future'
    else:proof['deliveryEventContractValid']=False
    assert project_annual_accounts_source(query,replace(snapshot,coverage=proof)).history_coverage.status=='incomplete'


@pytest.mark.parametrize('defect',['legacy','source2','duplicate','reverse','foreign-draft','future'])
def test_unrepresentable_or_ambiguous_event_extent_is_unavailable(draft,defect):
    query,snapshot=event_source(draft)
    if defect in ('legacy','source2'):snapshot=replace(snapshot,contract_version='annual-accounts-source-v1' if defect=='legacy' else 'annual-accounts-source-v2')
    elif defect=='duplicate':snapshot=replace(snapshot,delivery_events=snapshot.delivery_events*2)
    elif defect=='reverse':snapshot=replace(snapshot,delivery_events=tuple(reversed(snapshot.delivery_events)))
    elif defect=='foreign-draft':snapshot=replace(snapshot,delivery_drafts=())
    else:snapshot=replace(snapshot,as_of=snapshot.delivery_drafts[0].recorded_at)
    with pytest.raises(AnnualAccountsError):project_annual_accounts_source(query,snapshot)
