"""Fresh owner evidence is required before preparing a retained source preview."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from talli_backend.modules.documents.public import DocumentsError
from talli_backend.modules.shareholder_register_filing.public import (
    Rf1086YearSourceError,Rf1086YearSourceId,prepare_rf1086_year_source,
)
from talli_backend.shared.kernel import CompanyId,CorrelationId,IncomeYear
from test_shareholder_register_source_workflow import Harness
from test_shareholder_register_capital_source_workflow import setup,prepare_capital
from test_rf1086_year_source import COMPANY,YEAR,NOW


def preview(h,source_id=None,company_id=COMPANY,income_year=YEAR,**extra):
    return asyncio.run(h.workflow.generate_source_preview('current-owner-token',company_id=company_id,
        income_year=income_year,source_id=source_id or h.saved[0].source_id,
        correlation_id=CorrelationId('source-preview-evidence'),**extra))


def correction(h):
    original=h.saved[0]
    command=replace(original.command,supersedes_source_id=original.source_id,
        supersedes_source_sha256=original.source_sha256,correction_reason='New reviewed source')
    return prepare_rf1086_year_source(command,context=h.context,source_id=Rf1086YearSourceId(str(uuid4())),
        confirmed_at=NOW+timedelta(seconds=1),previous=original)


@pytest.mark.parametrize('kind',['no_activity','formation','transfer','dividend','cash_issue','loss_covering_reduction'])
def test_source_preview_reverifies_all_owner_evidence_and_uses_exact_retained_source(kind):
    h=setup(kind) if kind in {'cash_issue','loss_covering_reduction'} else Harness(kind)
    if kind in {'cash_issue','loss_covering_reduction'}:prepare_capital(h)
    source=h.capture();h.calls=[]
    result=preview(h)
    assert result.source_id==source.source_id and result.source_sha256==source.source_sha256
    assert result.case_sha256==source.case_sha256 and result.hovedskjema_xml
    assert h.preview_commands[0].source is source
    assert h.calls[:5]==['rf_auth','read_source','company','verify_document','governance']
    assert h.calls[-2:]==['read_current_source','preview_persist']
    if kind in {'cash_issue','loss_covering_reduction'}:assert 'read_current_observation' in h.calls
    assert len(h.saved)==1


@pytest.mark.parametrize('change',['missing','wrong_company','wrong_year','corrupt_source'])
def test_unavailable_or_invalid_source_cannot_reach_evidence_or_preview_persistence(change):
    h=Harness();source=h.capture();h.calls=[];kwargs={}
    if change=='missing':h.sources={}
    if change=='wrong_company':kwargs['company_id']=CompanyId(str(uuid4()))
    if change=='wrong_year':kwargs['income_year']=IncomeYear(2024)
    if change=='corrupt_source':h.sources[source.source_id]=replace(source,case_sha256='f'*64)
    with pytest.raises(Rf1086YearSourceError):preview(h,**kwargs)
    assert 'verify_document' not in h.calls and not h.previews


@pytest.mark.parametrize('change',['reviewer','changed_company','unconfirmed','changed_metadata','changed_bytes','bytes_missing','governance_added','governance_receipt_changed','governance_rejected'])
def test_changed_owner_identity_documents_or_governance_prevents_preview(change):
    h=Harness('dividend');h.capture()
    if change=='reviewer':h.company.role='reviewer'
    if change=='changed_company':h.company.address='Changed authoritative address'
    if change=='unconfirmed':h.company.identity_confirmed_at=None
    if change=='changed_metadata':h.record=replace(h.record,name='New original metadata')
    if change=='changed_bytes':h.record=replace(h.record,content_sha256='e'*64)
    if change=='bytes_missing':h.document_failure=True
    if change=='governance_added':h.view=replace(h.view,enumeration_sha256='e'*64)
    if change=='governance_receipt_changed':
        item=h.view.dividends[0]
        h.view=replace(h.view,dividends=(replace(item,finalizations=(replace(item.finalizations[0],created_at=NOW+timedelta(seconds=1)),)),))
    if change=='governance_rejected':h.view=replace(h.view,dividends=(replace(h.view.dividends[0],status='rejected'),))
    with pytest.raises((Rf1086YearSourceError,DocumentsError)):preview(h)
    assert not h.previews and not h.preview_commands


@pytest.mark.parametrize('during_io',[False,True])
def test_source_superseded_before_or_during_external_checks_prevents_preview(during_io):
    h=Harness();h.capture();new=correction(h)
    if during_io:h.after_document_verification=lambda:setattr(h,'current_source',new)
    else:h.current_source=new
    with pytest.raises(Rf1086YearSourceError,match='source_changed'):preview(h)
    assert not h.previews and not h.preview_commands


def test_source_superseded_after_owner_checks_is_rejected_by_persistence_lock():
    h=Harness();h.capture();h.preview_race=True
    with pytest.raises(Rf1086YearSourceError,match='source_changed'):preview(h)
    assert len(h.preview_commands)==1 and not h.previews


def test_superseded_register_observation_invalidates_capital_preview():
    h=setup();prepare_capital(h);h.capture();h.observation=None
    with pytest.raises(Rf1086YearSourceError,match='independent_register_unavailable'):preview(h)
    assert not h.previews


@pytest.mark.parametrize('capital',[False,True])
def test_current_accepted_owner_can_preview_original_captured_by_another_owner(capital):
    h=setup() if capital else Harness()
    if capital:prepare_capital(h)
    source=h.capture();h.actor=replace(h.actor,subject=type(h.actor.subject)(str(uuid4())))
    h.document_actor=h.actor
    assert preview(h).source_id==source.source_id
    assert h.preview_commands[0].source.command.actor_id==source.confirmed_by
    assert h.actor!=source.confirmed_by


def test_missing_current_head_prevents_preview():
    h=Harness();h.capture();h.current_source=None
    with pytest.raises(Rf1086YearSourceError,match='source_changed'):preview(h)
    assert not h.previews and not h.preview_commands


def test_changed_preview_result_cannot_be_returned_as_verified_source_preview():
    h=Harness();h.capture();h.preview_transform=lambda result:replace(result,source_sha256='e'*64)
    with pytest.raises(Rf1086YearSourceError,match='source_preview_mismatch'):preview(h)


@pytest.mark.parametrize('name',['case','context'])
def test_preview_does_not_accept_raw_case_or_trusted_context(name):
    h=Harness();h.capture();h.calls=[]
    with pytest.raises(TypeError):preview(h,**{name:object()})
    assert not h.calls and not h.previews
