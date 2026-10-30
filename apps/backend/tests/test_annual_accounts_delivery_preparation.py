"""Preparation replays committed originals and admits no unguarded source write."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC,datetime
from uuid import uuid4

import pytest

from talli_backend.adapters.annual_accounts_schemas import PinnedAnnualAccountsSchemas
from talli_backend.application.annual_accounts_delivery_preparation import AnnualAccountsDeliveryPreparation
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsError,AnnualAccountsRecordId,PrepareAnnualAccountsDeliveryDraft,StoredAnnualAccountsDeliveryDraft,
)
from talli_backend.shared.kernel import CorrelationId,IdempotencyKey,Timestamp,ActorId,ActorKind,UserId
from test_annual_accounts_delivery_source import ACTOR,COMPANY,YEAR,source_inputs,prepare,read
from test_annual_accounts_delivery_draft import delivery_snapshot


def command():return PrepareAnnualAccountsDeliveryDraft(COMPANY,YEAR,ACTOR,AnnualAccountsRecordId(str(uuid4())),
    IdempotencyKey(uuid4().hex),CorrelationId('accounts-delivery-prepare-test'),'owner@example.test','Synthetic Person')


class Session:
    actor_id=ACTOR
    def __init__(self):
        self.inputs,self.corporate,_=source_inputs();_,self.history=delivery_snapshot(prepare(read(self.inputs,self.corporate)))
        self.history=replace(self.history,delivery_drafts=(),coverage=dict(self.history.coverage)|{'deliveryDraftCount':0,'deliveryDraftDigests':{}})
        self.stored=None;self.events=[];self.guard=False;self.reject_snapshot=False;self.expire_after_source=False
    @asynccontextmanager
    async def transaction(self,*,snapshot=False):
        if snapshot and self.reject_snapshot:raise AssertionError('Replay attempted a fresh source read.')
        session=self
        class Transaction:
            actor_id=ACTOR
            delivery_corporate_queries=session.inputs.delivery_corporate_queries
            delivery_ledger_queries=session.inputs.delivery_ledger_queries
            async def delivery_annual_interview_history(self,query):
                assert session.guard and snapshot
                return session.inputs.history
            async def filing_source_snapshot(self,query):
                assert session.guard and snapshot
                session.events.append('history-read');return session.history
            async def delivery_draft_by_key(self,query,key):
                assert not snapshot
                return session.stored if session.stored and session.stored.draft.command_key==key else None
            async def lock_delivery_archive(self,query):
                assert not snapshot
                if session.expire_after_source and 'history-read' in session.events:raise AnnualAccountsError.mfa_required()
                session.events.append('guard');session.guard=True
            async def store_delivery_draft(self,draft):
                assert not snapshot and session.guard and session.events[-1]=='guard'
                session.events.append('store');session.stored=StoredAnnualAccountsDeliveryDraft(draft,Timestamp(datetime.now(UTC)))
                return session.stored
        try:yield Transaction()
        finally:
            if not snapshot:session.guard=False


def run(session,cmd):return asyncio.run(AnnualAccountsDeliveryPreparation(session.corporate,PinnedAnnualAccountsSchemas()).prepare(session,cmd))


def test_guarded_current_source_is_stored_once_and_lost_response_replays_exact_original():
    session=Session();cmd=command();stored=run(session,cmd)
    assert stored.draft.filing_id==str(cmd.filing_id) and session.events==['guard','history-read','guard','store']
    session.reject_snapshot=True
    session.inputs.history[0]['annualFullTimeEquivalents']=None
    assert run(session,cmd)==stored
    assert session.events.count('store')==1
    for changed in (replace(cmd,filing_id=AnnualAccountsRecordId(str(uuid4()))),
                    replace(cmd,contact_email='changed@example.test'),replace(cmd,confirming_representative='Changed Person')):
        with pytest.raises(AnnualAccountsError) as error:run(session,changed)
        assert error.value.code=='ANNUAL_ACCOUNTS_DELIVERY_DRAFT_CONFLICT'


@pytest.mark.parametrize('defect',['mfa-expired','incomplete-history','unreadable-events','legacy','unrepresentable-source','actor'])
def test_source_or_authorization_failure_leaves_no_draft(defect):
    session=Session();cmd=command()
    if defect=='mfa-expired':session.expire_after_source=True
    elif defect=='incomplete-history':session.history=replace(session.history,coverage=None)
    elif defect=='unreadable-events':session.history=replace(session.history,coverage=dict(session.history.coverage)|{'deliveryEventCount':1})
    elif defect=='legacy':session.history=replace(session.history,contract_version='annual-accounts-source-v1')
    elif defect=='unrepresentable-source':session.inputs.history[0]['annualFullTimeEquivalents']=None
    else:cmd=replace(cmd,actor_id=ActorId(ActorKind.USER,UserId(str(uuid4()))))
    with pytest.raises(AnnualAccountsError):run(session,cmd)
    assert session.stored is None and 'store' not in session.events and session.guard is False
