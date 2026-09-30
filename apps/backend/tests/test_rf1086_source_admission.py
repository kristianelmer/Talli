"""Same-scope evidence policy: bytes before guard, all consequential reads inside."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from talli_backend.application.shareholder_register_source_admission import (
    ShareholderRegisterSourceAdmission, Rf1086AdmissionCompany,
)
from talli_backend.modules.documents.public import RetainedDocumentOriginalReceipt, VerifiedDocumentEvidence
from talli_backend.modules.shareholder_register_filing import public as rf
from test_shareholder_register_source_workflow import Harness, dividend_view
from test_rf1086_year_source import ACTOR, COMPANY, YEAR, NOW
from talli_backend.shared.kernel import CorrelationId


class AdmissionHarness:
    def __init__(self, kind='no_activity'):
        self.source_harness = h = Harness(kind)
        self.source = h.capture()
        self.preview = asyncio.run(h.workflow.generate_source_preview('token', company_id=COMPANY,
            income_year=YEAR, source_id=self.source.source_id, correlation_id=CorrelationId('preview')))
        self.original = RetainedDocumentOriginalReceipt(str(uuid4()), h.record.document_id, COMPANY,
            h.record.income_year, self.source.command.documents[0].metadata_sha256,
            h.record.content_sha256, h.record.byte_length, NOW)
        self.current = self.source
        self.identity = Rf1086AdmissionCompany(h.command.case.company, h.company.identity_confirmed_at, h.company.identity_locked_at)
        self.view = h.view
        self.calls, self.held, self.committed = [], False, False
        self.document_actor, self.actor = ACTOR, ACTOR
        self.receipt_failure = False
        self.on_guard = lambda: None
        owner = self
        class Transaction:
            actor_id = ACTOR
            async def company_identity(self):
                assert owner.held; owner.calls.append('identity'); return owner.identity
            async def current_source(self):
                assert owner.held; owner.calls.append('source'); return owner.current
            async def source_preview(self, preview_id):
                assert owner.held; owner.calls.append('preview'); return owner.preview
            async def assert_original(self, receipt):
                assert owner.held; owner.calls.append('original')
                if owner.receipt_failure: raise rf.Rf1086YearSourceError('rf1086_source_documents_unverified')
                assert receipt == owner.original
            async def governance_evidence(self, correlation_id):
                assert owner.held; owner.calls.append('governance'); return owner.view
            async def read_current_register_observation(self, query, observation_id):
                assert owner.held; owner.calls.append('register'); return h.observation
        self.transaction = Transaction()
        class Session:
            @property
            def actor_id(self): return owner.actor
            async def source_preview(self, preview_id):
                assert not owner.held; return owner.preview
            async def read_year_source(self, query, source_id):
                assert not owner.held; return owner.source
            @asynccontextmanager
            async def source_admission(self, query):
                assert not owner.held
                owner.on_guard(); owner.held = True; owner.calls.append('guard')
                try:
                    yield owner.transaction
                    owner.committed = True
                finally:
                    owner.held = False; owner.calls.append('release')
        class Sessions:
            async def session(self, token): return Session()
        class Documents:
            @property
            def actor_id(self): return owner.document_actor
            async def verify_document_evidence(self, document_id):
                assert not owner.held; owner.calls.append('bytes')
                return VerifiedDocumentEvidence(h.record,h.record.content_sha256,h.record.byte_length,h.record.status,owner.original)
        class DocumentsFactory:
            async def session(self, token): return Documents()
        self.workflow = ShareholderRegisterSourceAdmission(Sessions(), DocumentsFactory())

    async def run(self, *, fail_consumer=False):
        async with self.workflow.admit('token',company_id=COMPANY,income_year=YEAR,
                preview_id=self.preview.preview_id,correlation_id=CorrelationId('admit')) as admitted:
            assert self.held
            assert admitted.source == self.source and admitted.preview == self.preview
            assert admitted.transaction is self.transaction and admitted.originals == (self.original,)
            self.calls.append('decision_write')
            if fail_consumer: raise RuntimeError('decision aborted')


@pytest.mark.parametrize('kind', ['no_activity','formation','transfer','dividend'])
def test_all_source_policy_runs_inside_guard_after_external_original_bytes(kind):
    h = AdmissionHarness(kind)
    asyncio.run(h.run())
    assert h.calls == ['bytes','guard','identity','source','preview','original','governance','decision_write','release']
    assert h.committed and not h.held


@pytest.mark.parametrize('mutation', ['identity','confirmation','governance','source','original'])
def test_changes_committed_during_preflight_prevent_any_consequential_write(mutation):
    h = AdmissionHarness()
    def change():
        if mutation == 'identity': h.identity = replace(h.identity,company=replace(h.identity.company,name='Renamed AS'))
        if mutation == 'confirmation': h.identity = replace(h.identity,identity_locked_at='2026-09-01T00:00:00+00:00')
        if mutation == 'governance': h.view = replace(h.view,enumeration_sha256='e'*64)
        if mutation == 'source': h.current = rf.prepare_rf1086_year_source(h.source.command,context=h.source_harness.context,
            source_id=rf.Rf1086YearSourceId(str(uuid4())),confirmed_at=NOW)
        if mutation == 'original': h.receipt_failure = True
    h.on_guard = change
    with pytest.raises(rf.Rf1086YearSourceError): asyncio.run(h.run())
    assert 'decision_write' not in h.calls and not h.committed and not h.held


def test_consumer_failure_rolls_back_before_releasing_guard():
    h=AdmissionHarness()
    with pytest.raises(RuntimeError,match='decision aborted'): asyncio.run(h.run(fail_consumer=True))
    assert not h.committed and h.calls[-1]=='release'


@pytest.mark.parametrize('mutation', ['missing','company','year','hash','metadata','length','id'])
def test_preflight_requires_exact_retained_original_receipt(mutation):
    h=AdmissionHarness()
    if mutation=='missing': h.original=None
    if mutation=='company': h.original=replace(h.original,company_id=type(COMPANY)(str(uuid4())))
    if mutation=='year': h.original=replace(h.original,source_income_year=type(YEAR)(2023))
    if mutation=='hash': h.original=replace(h.original,content_sha256='f'*64)
    if mutation=='metadata': h.original=replace(h.original,metadata_sha256='f'*64)
    if mutation=='length': h.original=replace(h.original,byte_length=1)
    if mutation=='id': h.original=replace(h.original,document_id=type(h.original.document_id)(str(uuid4())))
    with pytest.raises(rf.Rf1086YearSourceError): asyncio.run(h.run())
    assert h.calls==['bytes'] and not h.committed


def test_guarded_legal_identity_preserves_reviewed_contact_and_share_type():
    h=AdmissionHarness()
    # Rebuild through the real capture policy after changing an RF-owned field.
    source_h=h.source_harness
    source_h.command=replace(source_h.command,case=replace(source_h.command.case,
        company=replace(source_h.command.case.company,contact_email='owner@example.invalid')))
    h.source=source_h.capture(); h.current=h.source
    h.preview=asyncio.run(source_h.workflow.generate_source_preview('token',company_id=COMPANY,
        income_year=YEAR,source_id=h.source.source_id,correlation_id=CorrelationId('contact-preview')))
    h.identity=replace(h.identity,company=replace(h.identity.company,contact_email=None))
    assert h.identity.company.contact_email is None
    asyncio.run(h.run())
    assert h.committed


def test_review_projection_commits_only_after_all_admission_checks_inside_guard():
    h=AdmissionHarness()
    async def bridge(preview):
        assert h.held and 'governance' in h.calls and 'original' in h.calls
        assert preview == h.preview
        h.calls.append('bridge')
        return preview.preview_id
    h.transaction.bridge_source_preview=bridge
    result=asyncio.run(h.workflow.prepare_review('token',company_id=COMPANY,income_year=YEAR,
        preview_id=h.preview.preview_id,correlation_id=CorrelationId('review-bridge')))
    assert result==h.preview.preview_id and h.committed
    assert h.calls.index('bridge') < h.calls.index('release')


def test_stale_source_never_materializes_review_and_bridge_failure_rolls_back():
    h=AdmissionHarness()
    async def bridge(preview):
        assert h.held
        raise RuntimeError('projection write failed')
    h.transaction.bridge_source_preview=bridge
    with pytest.raises(RuntimeError,match='projection write failed'):
        asyncio.run(h.workflow.prepare_review('token',company_id=COMPANY,income_year=YEAR,
            preview_id=h.preview.preview_id,correlation_id=CorrelationId('review-bridge')))
    assert not h.committed and not h.held
    h.on_guard=lambda:setattr(h,'current',replace(h.source,source_sha256='f'*64))
    with pytest.raises(rf.Rf1086YearSourceError):
        asyncio.run(h.workflow.prepare_review('token',company_id=COMPANY,income_year=YEAR,
            preview_id=h.preview.preview_id,correlation_id=CorrelationId('review-bridge')))
    assert not h.committed
