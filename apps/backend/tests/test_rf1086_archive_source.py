"""The archive reads one filing year plus its original company-wide evidence."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import pytest

from talli_backend.modules.shareholder_register_filing.public import (
    Rf1086ArchiveQuery,Rf1086ArchiveSnapshot,Rf1086SimulationRecord,
    Rf1086ReviewCommentRecord,Rf1086FilingPermissionRecord,Rf1086TestEvidenceRecord,
    ShareholderRegisterFilingError,create_rf1086_preparation_service,
)
from talli_backend.shared.kernel import CompanyId,IncomeYear
from test_rf1086_preparation import ACTOR,COMPANY,YEAR,NOW,CASES,preview

QUERY=Rf1086ArchiveQuery(COMPANY,YEAR,ACTOR)
OTHER=CompanyId('10000000-0000-4000-8000-000000000009')
EVIDENCE='60000000-0000-4000-8000-000000000006'


def simulation():
    case=CASES[0];result=case['result']
    return Rf1086SimulationRecord('50000000-0000-4000-8000-000000000005',preview().id,EVIDENCE,
        str(COMPANY),2025,preview().filing,'test_authority','test_authority',case['payload_hash'],case['idempotency_key'],
        result['status'],tuple(result['calls']),result['receipt_id'],tuple(result['feedback_document_ids']),
        tuple(case['feedback_items']),case['receipt_metadata'],case['submitted_payload_ref'],case['submitted_payload'],
        result['authority_confirmed_at'],result['preview_confirmed_at'],NOW,NOW,str(ACTOR.subject))


def snapshot():
    # This company-wide comment intentionally refers to a different year's
    # preview, whose payload must never be needed to read the comment.
    comment=Rf1086ReviewCommentRecord('comment','other-year-preview',str(COMPANY),'rf1086_preview',
        'advisory','Retained company-wide note',str(ACTOR.subject),None,None,NOW)
    permission=Rf1086FilingPermissionRecord('permission',str(COMPANY),'aksjonaerregisteroppgaven',
        str(ACTOR.subject),str(ACTOR.subject),NOW,False,NOW)
    evidence=Rf1086TestEvidenceRecord(EVIDENCE,str(COMPANY),'aksjonaerregisteroppgaven','manual_evidence',
        'accepted','original-reference','original-summary',None,None,None,None,str(ACTOR.subject),NOW)
    return Rf1086ArchiveSnapshot(COMPANY,YEAR,(preview(),),(simulation(),),(comment,),(permission,),(evidence,))


class Store:
    def __init__(self,result):self.result=result;self.queries=[]
    async def archive_source(self,query):self.queries.append(query);return self.result
    async def workspace(self,query):raise AssertionError('Archive must not request all-year workspace')


def read(result):return asyncio.run(create_rf1086_preparation_service(Store(result)).archive_source(QUERY))


def test_archive_preserves_exact_selected_payload_and_company_wide_comment_without_parent_decode():
    original=snapshot();store=Store(original)
    result=asyncio.run(create_rf1086_preparation_service(store).archive_source(QUERY))
    assert result is original and store.queries==[QUERY]
    assert result.review_comments[0].preview_id not in {p.id for p in result.previews}
    assert result.simulations[0].submitted_payload==simulation().submitted_payload
    with pytest.raises(TypeError):result.simulations[0].submitted_payload['incomeYear']=2024
    assert not hasattr(result,'production_submissions') and not hasattr(result,'approvals')


@pytest.mark.parametrize('change',[{'company_id':str(COMPANY)},{'income_year':None},{'income_year':2025},{'actor_id':str(ACTOR.subject)}])
def test_archive_query_requires_explicit_typed_scope(change):
    with pytest.raises(ShareholderRegisterFilingError):replace(QUERY,**change)


@pytest.mark.parametrize('change',[{'company_id':OTHER},{'income_year':IncomeYear(2024)}])
def test_archive_snapshot_scope_must_match_verified_query(change):
    with pytest.raises(ShareholderRegisterFilingError):read(replace(snapshot(),**change))


@pytest.mark.parametrize('field',['previews','simulations','review_comments','permissions','test_evidence'])
def test_archive_rejects_cross_company_rows_before_publishing(field):
    original=snapshot();record=getattr(original,field)[0]
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,**{field:(replace(record,company_id=str(OTHER)),)}))


@pytest.mark.parametrize('field',['previews','simulations'])
def test_archive_rejects_another_year_and_another_obligation(field):
    original=snapshot();record=getattr(original,field)[0]
    for change in ({'income_year':2024},{'filing':'skattemelding'}):
        with pytest.raises(ShareholderRegisterFilingError):read(replace(original,**{field:(replace(record,**change),)}))


@pytest.mark.parametrize('field',['permissions','test_evidence'])
def test_archive_rejects_sibling_obligation_evidence(field):
    original=snapshot();record=getattr(original,field)[0]
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,**{field:(replace(record,obligation='skattemelding'),)}))


@pytest.mark.parametrize('field',['previews','simulations','review_comments','permissions','test_evidence'])
def test_archive_rejects_duplicate_source_identity(field):
    original=snapshot();record=getattr(original,field)[0]
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,**{field:(record,record)}))


def test_archive_rejects_sibling_comment_target_and_unreferenced_evidence():
    original=snapshot()
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,review_comments=(replace(original.review_comments[0],target='company_tax_preview'),)))
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,test_evidence=(*original.test_evidence,replace(original.test_evidence[0],id='not-referenced'))))
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,test_evidence=()))


def test_simulation_mode_does_not_pull_authority_evidence_and_empty_year_is_retained():
    original=snapshot();result=replace(original,simulations=(replace(simulation(),mode='simulation'),),test_evidence=())
    assert read(result) is result
    empty=Rf1086ArchiveSnapshot(COMPANY,YEAR,review_comments=original.review_comments,permissions=original.permissions)
    assert read(empty) is empty


@pytest.mark.parametrize('field',['previews','simulations','review_comments','permissions','test_evidence'])
def test_archive_rejects_untyped_rows(field):
    with pytest.raises(ShareholderRegisterFilingError):read(replace(snapshot(),**{field:({'company_id':str(COMPANY)},)}))
