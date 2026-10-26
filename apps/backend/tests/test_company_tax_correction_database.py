"""Actual signed owner/MFA, owning reads, HTTP parent/current and child dispatch."""
import asyncio
from contextlib import contextmanager
from datetime import datetime,UTC,timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg.types.json import Jsonb
from psycopg import sql
import pytest

from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.adapters.loopback_company_tax_intake import LoopbackCompanyTaxIntake
from talli_backend.adapters.loopback_company_tax_parent_read import LoopbackCompanyTaxParentRead
from talli_backend.application.company_tax_delivery_preparation import CompanyTaxDeliveryPreparation
from talli_backend.application.company_tax_intake_rehearsal import TaxCurrentIntakeRehearsalAdmission,TaxCurrentIntakeRehearsalRuntime
from talli_backend.application.company_tax_parent_read_rehearsal import TaxParentReadRehearsalAdmission,TaxParentReadRehearsalRuntime
from talli_backend.main import create_app
from talli_backend.modules.company_tax_filing.public import CompanyTaxSourceQuery,PrepareTaxDeliveryDraft,TaxFilingSubmissionId
from talli_backend.shared.kernel import Timestamp,IdempotencyKey,CorrelationId
from test_company_tax_current_intake_database import signed_runtime,current_intake_http,retained
from test_company_tax_delivery_observations_database import finite_http
from test_company_tax_final_submission_database import reviewed,ADVANCE,RECONCILE
from test_company_tax_correction import current_pair

pytestmark=pytest.mark.company_tax_database
ROUTE='/api/v1/company-tax/delivery-corrections'


async def stored_journal(signed_runtime,filing):
    connection,token,_=signed_runtime;session=await connection[4].session(token)
    query=CompanyTaxSourceQuery(filing.envelope.source.company_id,filing.envelope.source.income_year,connection[3])
    async with session.transaction(snapshot=True) as tx:return await tx.delivery_journal(query,filing.filing_id)


@contextmanager
def correction_http(signed_runtime,*,reconcile=True):
    connection,token,aal1=signed_runtime;url,_,cid,actor,sessions=connection
    with current_intake_http(signed_runtime) as (initial,app,command,body,headers,_,_,original,*_):
        assert initial.post('/api/v1/company-tax/delivery-drafts',json=body,headers=headers).status_code==200
        draft=retained(app,command,token).draft
        with finite_http(signed_runtime,submission=True,prepared_current=(command,draft,original)) as (parent_client,_,wire,_,_):
            advance,headers,confirm=reviewed(parent_client,draft,token)
            assert parent_client.post(ADVANCE,json=confirm,headers=headers).json()['status']=='uncertain'
            wire.update(terminal=True,receiptBytes=b'\xef\xbb\xbf <opaque-parent-receipt/>\n\xff')
            if reconcile:assert parent_client.post(RECONCILE,json=advance,headers=headers).json()['status']=='mutation_completed'
            parent=asyncio.run(stored_journal(signed_runtime,draft));events={e.slot:e.value for e in parent.events}
            pair={d.document_type:d.raw_bytes for d in events['intent:prepare_confirmation'].confirmation_prerequisite.calculated.response.calculated_documents}
            current=current_pair(parent,pair,Timestamp(datetime.now(UTC)),reference='current-after-terminal-parent')
            grant=wire['grant'];now=Timestamp(datetime.now(UTC))
            scope=TaxCurrentIntakeRehearsalAdmission(str(uuid4()),command.company_id,command.income_year,actor,draft.envelope.source.organization_number,
                now,Timestamp(now.value+timedelta(minutes=5)),grant.origin,uuid4().hex+uuid4().hex,grant.database_scope_sha256,3)
            read=TaxParentReadRehearsalAdmission(scope,draft.filing_id,draft.sha256,parent.approval.sha256,events['completion:create_instance'].result['instanceId'])
            intake=TaxCurrentIntakeRehearsalAdmission(str(uuid4()),scope.company_id,scope.income_year,actor,scope.organization_number,
                now,scope.expires_at,scope.origin,uuid4().hex+uuid4().hex,scope.database_scope_sha256,2)
            wire.update(parentReadGrant=read,intakeGrant=intake,currentBytes=current.raw_bytes)
            preparation=CompanyTaxDeliveryPreparation(None,PinnedTax2025Schemas(),
                intake=LoopbackCompanyTaxIntake(TaxCurrentIntakeRehearsalRuntime(intake)),
                parent_reader=LoopbackCompanyTaxParentRead(TaxParentReadRehearsalRuntime(read)))
            client=TestClient(create_app(company_tax_session_factory=sessions,company_tax_delivery_preparation=preparation))
            child_id=str(uuid4());key='signed-correction-'+uuid4().hex
            command_body={'companyId':str(cid),'incomeYear':2025,'filingId':child_id,'parentFilingId':draft.filing_id,
                'parentDraftSha256':draft.sha256,'parentApprovalSha256':parent.approval.sha256}
            child_headers={'Authorization':'Bearer '+token,'Idempotency-Key':key}
            try:yield client,parent,command_body,child_headers,wire,current,preparation
            finally:client.close()


def change_owning_ledger_fixture(signed_runtime):
    """Synthetic source fixture only; real owning readers enumerate these rows."""
    connection,_,_=signed_runtime;url,_,cid,actor,_=connection
    with psycopg.connect(url) as db:
        db.execute('update public.annual_data set no_activity_confirmed=false where company_id=%s and income_year=2025',(cid,))
        principal=db.execute('select current_user').fetchone()[0]
        before=db.execute("select admin_option,inherit_option,set_option from pg_auth_members where roleid='ledger_store_owner'::regrole and member=pg_catalog.to_regrole(current_user) and grantor=member").fetchone()
        missing=not db.execute("select has_table_privilege(current_user,'ledger.entries','INSERT')").fetchone()[0]
        db.execute(sql.SQL('grant ledger_store_owner to {} with set true granted by {}').format(sql.Identifier(principal),sql.Identifier(principal)))
        if missing:
            db.execute('set local role ledger_store_owner')
            db.execute(sql.SQL('grant insert on ledger.entries to {}').format(sql.Identifier(principal)))
            db.execute('reset role')
        db.execute("insert into ledger.entries(company_id,income_year,entry_kind,memo,lines,created_by,source_capability,source_record_id,correlation_id) values(%s,2025,'BANK_INTEREST','Synthetic correction interest',%s,%s,'BANKING',%s,%s)",
            (cid,Jsonb([{'account':'1920','description':'Synthetic bank interest','debit':'100.00','credit':'0.00','currency':'NOK'},
                {'account':'8050','description':'Synthetic interest income','debit':'0.00','credit':'100.00','currency':'NOK'}]),str(actor.subject),str(uuid4()),str(uuid4())))
        if missing:
            db.execute('set local role ledger_store_owner')
            db.execute(sql.SQL('revoke insert on ledger.entries from {}').format(sql.Identifier(principal)))
            db.execute('reset role')
        db.execute(sql.SQL('revoke ledger_store_owner from {} granted by {}').format(sql.Identifier(principal),sql.Identifier(principal)))
        if before is not None:
            db.execute(sql.SQL('grant ledger_store_owner to {} with admin {},inherit {},set {} granted by {}').format(
                sql.Identifier(principal),sql.SQL(str(before[0]).lower()),sql.SQL(str(before[1]).lower()),sql.SQL(str(before[2]).lower()),sql.Identifier(principal)))
        assert db.execute("select admin_option,inherit_option,set_option from pg_auth_members where roleid='ledger_store_owner'::regrole and member=pg_catalog.to_regrole(current_user) and grantor=member").fetchone()==before


def test_signed_correction_fresh_parent_and_current_reads_store_a_distinct_complete_changed_packet(signed_runtime):
    connection,token,aal1=signed_runtime;url,_,cid,actor,sessions=connection
    with correction_http(signed_runtime) as (client,parent,body,headers,wire,_,_):
        before=len(wire['calls'])
        assert client.post(ROUTE,json=body,headers=headers|{'Authorization':'Bearer '+aal1}).status_code==403
        assert len(wire['calls'])==before
        change_owning_ledger_fixture(signed_runtime)
        response=client.post(ROUTE,json=body,headers=headers)
        assert response.status_code==200,response.status_code
        assert [method for method,_ in wire['calls'][before:]]==['GET']*4
        async def read_child():
            session=await sessions.session(token)
            async with session.transaction() as tx:return await tx.delivery_draft_by_key(CompanyTaxSourceQuery(parent.draft.envelope.source.company_id,
                parent.draft.envelope.source.income_year,actor),IdempotencyKey(headers['Idempotency-Key']))
        stored=asyncio.run(read_child());child=stored.draft
        assert child.correction_parent.filing_id==parent.draft.filing_id
        assert len(child.envelope.source.ledger_entries)==1 and '<beloepSomHeltall>100</beloepSomHeltall>' in child.envelope.tax_xml
        assert child.envelope.source.source_sha256!=parent.draft.envelope.source.source_sha256
        count=len(wire['calls']);assert client.post(ROUTE,json=body,headers=headers).json()==response.json()
        assert len(wire['calls'])==count
        params={'companyId':str(cid),'incomeYear':2025,'readEvidence':True,'readEvidenceVersion':2,'validationEvidence':True,
            'confirmationEvidence':True,'submissionEvidence':True,'correctionEvidence':True}
        prepared_archive=client.get('/api/v1/company-tax/archive-source/delivery-journal-v1',params=params,headers=headers)
        assert prepared_archive.status_code==200
        import json,subprocess
        prepared_value=prepared_archive.json()
        checked=subprocess.run(['node','--experimental-strip-types','tests/support/check-tax-journal-client.mjs'],
            input=json.dumps({'archive':prepared_value,'source':prepared_value['sourceFacts'],'testCorrectionCorruptions':True}),text=True,capture_output=True)
        assert checked.returncode==0,checked.stderr[-2000:]
        command=PrepareTaxDeliveryDraft(child.envelope.source.company_id,child.envelope.source.income_year,actor,
            TaxFilingSubmissionId(child.filing_id),child.command_key,CorrelationId('signed-correction-child'))
        with finite_http(signed_runtime,submission=True,prepared_current=(command,child,child.current_document.response),
                instance_id=parent.draft.current_document.party_number+'/'+str(uuid4())) as (delivery,_,child_wire,_,_):
            advance,owner_headers,confirm=reviewed(delivery,child,token)
            assert delivery.post(ADVANCE,json=confirm,headers=owner_headers).json()['status']=='uncertain'
            child_wire.update(terminal=True,receiptBytes=b'\xef\xbb\xbf <opaque-child-receipt/>\n\xff')
            assert delivery.post(RECONCILE,json=advance,headers=owner_headers).json()['status']=='mutation_completed'
            assert child_wire['submissionPuts']==1
            # The complete archive contains both immutable original generations.
            archive=delivery.get('/api/v1/company-tax/archive-source/delivery-journal-v1',params={
                'companyId':str(cid),'incomeYear':2025,'readEvidence':True,'readEvidenceVersion':2,'validationEvidence':True,
                'confirmationEvidence':True,'submissionEvidence':True,'correctionEvidence':True},headers=owner_headers)
            assert archive.status_code==200
            value=archive.json();assert value['draftCount']==2
            assert next(row['canonicalJson'] for row in value['drafts'] if row['filingId']==parent.draft.filing_id)==parent.draft.canonical_json
            import json,subprocess,os
            checked=subprocess.run(['node','--experimental-strip-types','tests/support/check-tax-journal-client.mjs'],
                input=json.dumps({'archive':value,'source':value['sourceFacts']}),text=True,capture_output=True)
            assert checked.returncode==0,checked.stderr[-2000:]


def test_signed_unresolved_parent_blocks_correction_before_any_extra_http(signed_runtime):
    with correction_http(signed_runtime,reconcile=False) as (client,_,body,headers,wire,_,_):
        before=len(wire['calls']);assert client.post(ROUTE,json=body,headers=headers).status_code==409
        assert len(wire['calls'])==before


@pytest.mark.parametrize('stage',['metadata','receipt','file','current'])
def test_signed_access_loss_between_correction_reads_blocks_following_read_and_child_storage(signed_runtime,stage):
    connection,_,_=signed_runtime;url,_,cid,actor,_=connection
    with correction_http(signed_runtime) as (client,_,body,headers,wire,_,_):
        def revoke():
            with psycopg.connect(url) as db:db.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',(cid,str(actor.subject)))
        wire[{'metadata':'onInstance','receipt':'onFeedback','file':'onFile','current':'onCurrent'}[stage]]=revoke
        before=len(wire['calls']);result=client.post(ROUTE,json=body,headers=headers)
        assert result.status_code in (403,404)
        assert len(wire['calls'])-before=={'metadata':1,'receipt':2,'file':3,'current':4}[stage]
        with psycopg.connect(url) as db:
            assert db.execute('select count(*) from company_tax_filing.delivery_drafts where id=%s',(body['filingId'],)).fetchone()==(0,)
