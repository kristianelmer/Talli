"""Archive complete originals; source uncertainty never becomes false absence."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta

import pytest

from talli_backend.application.company_tax_filing_workflow import CompanyTaxApplication
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,CompanyTaxSourceQuery,StoredTaxDeliveryEvent,TaxMutationKind,
    archive_tax_delivery_journal,approve_tax_delivery_review,build_tax_delivery_mutation_request,
)
from talli_backend.shared.kernel import Timestamp
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_draft import delivery_snapshot


@pytest.fixture
def complete_archive(review_basis):
    draft=review_basis['draft'];approval=approve_tax_delivery_review(**review_basis)
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.CREATE_INSTANCE)
    _,snapshot=delivery_snapshot(draft)
    query=CompanyTaxSourceQuery(draft.envelope.source.company_id,draft.envelope.source.income_year,approval.approved_by)
    observed=Timestamp(draft.current_document.response.observed_at.value+timedelta(seconds=1))
    events=tuple(StoredTaxDeliveryEvent(value,observed,approval.approved_by) for value in (approval,request))
    proof=dict(snapshot.coverage)|{'companyId':str(query.company_id),'contractVersion':'company-tax-source-v3',
        'declaredDeliveryExtentValid':False,'declaredJournalExtentValid':True,
        'declaredTables':sorted((*snapshot.coverage['declaredTables'],'delivery_events')),
        'deliveryEventArchiveTrackingValid':True,'deliveryEventCount':2,
        'deliveryEventDigests':{event.binding.filing_id+':'+event.slot:event.value.sha256 for event in events}}
    snapshot=replace(snapshot,rows=replace(snapshot.rows,company_id=query.company_id,**{name:tuple(dict(row)|{'company_id':str(query.company_id)} for row in getattr(snapshot.rows,name)) for name in ('previews','submissions','overrides','review_comments','permissions','test_evidence')}),coverage=proof,
        contract_version='company-tax-source-v3',delivery_events=events,as_of=observed)
    return query,snapshot


def test_archive_keeps_one_complete_source_and_exact_originals(complete_archive):
    query,snapshot=complete_archive;result=archive_tax_delivery_journal(query,snapshot)
    assert result.drafts==snapshot.delivery_drafts and result.events==snapshot.delivery_events
    assert result.source_facts.history_coverage.status=='complete'
    assert result.source_facts.delivery_journals[0].status=='uncertain'
    assert not result.source_facts.production_attempts


@pytest.mark.parametrize('change',['version','proof','events','drafts','tracking','extent'])
def test_incomplete_archive_never_returns_partial_originals(complete_archive,change):
    query,snapshot=complete_archive
    if change=='version':snapshot=replace(snapshot,contract_version='company-tax-source-v2')
    elif change=='proof':snapshot=replace(snapshot,coverage=None)
    elif change=='events':snapshot=replace(snapshot,delivery_events=())
    elif change=='drafts':snapshot=replace(snapshot,delivery_drafts=())
    else:snapshot=replace(snapshot,coverage=dict(snapshot.coverage)|{
        'deliveryEventArchiveTrackingValid' if change=='tracking' else 'declaredJournalExtentValid':False})
    with pytest.raises(CompanyTaxError):archive_tax_delivery_journal(query,snapshot)


@pytest.mark.parametrize('deny_late',[False,True])
def test_application_holds_current_guard_across_snapshot_and_checks_again_before_return(complete_archive,deny_late):
    query,snapshot=complete_archive;order=[];active=[]
    class Sessions:
        actor_id=query.actor_id
        async def session(self,_token):return self
        @asynccontextmanager
        async def transaction(self,*,snapshot=False):
            active.append(snapshot)
            try:yield self
            finally:active.pop()
        async def lock_delivery_draft_archive(self,scope):
            assert scope==query and active==[False]
            order.append('guard')
            if deny_late and len(order)>1:raise CompanyTaxError.mfa_required()
        async def journal_history_snapshot(self,scope):
            assert scope==query and active==[False,True]
            order.append('snapshot')
            return snapshot
    async def exercise():return await (await CompanyTaxApplication(Sessions(),lambda tx:None).session('fixture')).delivery_journal_archive(query)
    if deny_late:
        with pytest.raises(CompanyTaxError):asyncio.run(exercise())
    else:assert asyncio.run(exercise()).source_facts.history_coverage.status=='complete'
    assert order==['guard','snapshot','guard']
