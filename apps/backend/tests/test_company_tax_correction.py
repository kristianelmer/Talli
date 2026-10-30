"""Terminal-only correction lineage, exact current pair and closed old codecs."""
import asyncio
import base64
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json
from uuid import uuid4

import httpx
import pytest

from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.adapters.loopback_company_tax_parent_read import LoopbackCompanyTaxParentRead
from talli_backend.application.company_tax_intake_rehearsal import TaxCurrentIntakeRehearsalAdmission
from talli_backend.application.company_tax_parent_read_rehearsal import TaxParentReadRehearsalAdmission,TaxParentReadRehearsalRuntime
from talli_backend.modules.company_tax_filing.public import (
    TaxDeliveryCorrectionParent,TaxDeliverySubmissionReadEvidence,TaxDeliveryJournal,TaxDeliveryDraft,
    decode_tax_delivery_draft,tax_delivery_lineage,prepare_tax_delivery,TaxCurrentDocumentIntakeQuery,
    TaxCurrentDocumentResponse,CompanyTaxError,
)
from talli_backend.shared.kernel import Timestamp,IdempotencyKey,CorrelationId
from test_company_tax_delivery_final_submission_workflow import (
    submission_workflow,confirmation_workflow,validation_workflow,upload_workflow,workflow,complete_archive,review_basis,reviewed,
)

pytestmark=pytest.mark.parametrize('workflow',[80],indirect=True)


async def terminal_basis(fixture):
    session,service,_,_,state,clock,*_=fixture
    command,recovery,_=await reviewed(fixture)
    await service.advance_submission(session,command)
    state.update(terminal=True,receiptBytes=b'\xef\xbb\xbf <opaque-parent-receipt/>\n\xff')
    await service.reconcile_submission(session,recovery)
    clock[0]=Timestamp(clock[0].value+timedelta(seconds=1))
    journal=TaxDeliveryJournal(session.draft,tuple(session.events),True,True,True,True,True,True)
    events={e.slot:e.value for e in journal.events};approval=journal.approval
    instance=await service._authority.observe_instance(approval,journal.draft,events['completion:create_instance'])
    feedback=await service._authority.observe_feedback(approval,journal.draft,events['completion:create_instance'],instance)
    envelope=await service._authority.observe_envelope(approval,journal.draft,events['completion:create_instance'],instance)
    pair={d.document_type:d.raw_bytes for d in events['intent:prepare_confirmation'].confirmation_prerequisite.calculated.response.calculated_documents}
    link=TaxDeliveryCorrectionParent(journal.draft.filing_id,journal.draft.sha256,approval.sha256,
        events['intent:confirm_submission'].sha256,events['completion:confirm_submission'].sha256,
        sha256(pair['skattemeldingUpersonligEtterBeregning']).hexdigest(),sha256(pair['naeringsspesifikasjonEtterBeregning']).hexdigest(),
        TaxDeliverySubmissionReadEvidence(instance,envelope,feedback))
    link.assert_parent(journal)
    return journal,link,pair,clock


def current_pair(parent,pair,observed,*,reference='fresh-current-reference',extra='',locked=''):
    ns='no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:forespoersel:response:v2'
    tax=base64.b64encode(pair['skattemeldingUpersonligEtterBeregning']).decode()
    business=base64.b64encode(pair['naeringsspesifikasjonEtterBeregning']).decode()
    raw=(f'\ufeff<skattemeldingOgNaeringsspesifikasjonforespoerselResponse xmlns="{ns}"><dokumenter>'
        f'<skattemeldingdokument><id>{reference}</id><encoding>utf-8</encoding><content>{tax}</content>'
        '<type>skattemeldingUpersonligFastsatt</type></skattemeldingdokument>'
        f'<naeringsspesifikasjondokument><id>known-parent-business</id><encoding>utf-8</encoding><content>{business}</content>'
        f'</naeringsspesifikasjondokument>{extra}</dokumenter>{locked}</skattemeldingOgNaeringsspesifikasjonforespoerselResponse>\n').encode()
    return TaxCurrentDocumentResponse(parent.draft.envelope.source.organization_number,parent.draft.envelope.source.income_year,
        base64.b64encode(raw).decode(),observed)


def child_draft(parent,link,pair,observed,*,source=None):
    schemas=PinnedTax2025Schemas();response=current_pair(parent,pair,observed)
    current=schemas.inspect_current(response,correction_parent=link)
    envelope=prepare_tax_delivery(source or parent.draft.envelope.source,party_number=current.party_number,
        current_document_reference=current.document_reference,schema_sha256=schemas.schema_sha256)
    return TaxDeliveryDraft(str(uuid4()),IdempotencyKey(uuid4().hex),parent.draft.prepared_by,envelope,
        schemas.validate(envelope,current_document=current,correction_parent=link),current,link)


def test_terminal_parent_and_current_pair_bind_v3_without_changing_prior_bytes(submission_workflow):
    async def exercise():
        parent,link,pair,clock=await terminal_basis(submission_workflow)
        prior=parent.draft.canonical_json
        child=child_draft(parent,link,pair,clock[0]);link.assert_current(clock[0])
        assert decode_tax_delivery_draft(child.canonical_json,child.sha256)==child
        assert json.loads(child.canonical_json)['version']=='company-tax-delivery-draft-v3'
        assert json.loads(prior)['version']=='company-tax-delivery-draft-v2'
        assert 'correction_parent' not in json.loads(prior)['draft'] and parent.draft.canonical_json==prior
        assert child.envelope.current_document_reference=='fresh-current-reference'
        assert child.current_document.response.raw_bytes.startswith(b'\xef\xbb\xbf')
        assert tax_delivery_lineage((parent,TaxDeliveryJournal(child,(),True,True,True,True,True,True)))==child.filing_id
        with pytest.raises(ValueError):TaxDeliveryJournal(child,(),True,True,True,True,True)
    asyncio.run(exercise())


@pytest.mark.parametrize('change',['draft','approval','request','completion','tax','business','active','missing-receipt','stale','future'])
def test_parent_identity_terminal_and_freshness_cannot_be_forged(submission_workflow,change):
    async def exercise():
        parent,link,_,clock=await terminal_basis(submission_workflow)
        if change in ('draft','approval','request','completion','tax','business'):
            name={'draft':'draft_sha256','approval':'approval_sha256','request':'submission_request_sha256',
                'completion':'submission_completion_sha256','tax':'calculated_tax_sha256','business':'calculated_business_sha256'}[change]
            with pytest.raises(ValueError):replace(link,**{name:'d'*64}).assert_parent(parent)
        elif change=='missing-receipt':
            with pytest.raises(ValueError):replace(link,terminal=replace(link.terminal,feedback=None))
        elif change=='active':
            raw=json.loads(link.terminal.instance.original.raw_bytes.decode('utf-8-sig'))
            raw['process']={'currentTask':{'altinnTaskType':'feedback','elementId':'Task_3','flow':3}}
            raw['status']={'isArchived':False}
            instance=replace(link.terminal.instance,original=replace(link.terminal.instance.original,
                body_base64=base64.b64encode(json.dumps(raw).encode()).decode()))
            feedback=replace(link.terminal.feedback,instance_evidence_sha256=instance.evidence_sha256)
            envelope=replace(link.terminal.envelope,instance_evidence_sha256=instance.evidence_sha256)
            with pytest.raises(ValueError):replace(link,terminal=TaxDeliverySubmissionReadEvidence(instance,envelope,feedback))
        else:
            when=Timestamp(clock[0].value+timedelta(seconds=31 if change=='stale' else -1))
            with pytest.raises(ValueError):link.assert_current(when)
    asyncio.run(exercise())


@pytest.mark.parametrize('change',['tax','business','guidance','locked','no-context'])
def test_correction_current_cannot_discard_unknown_or_different_authority_facts(submission_workflow,change):
    async def exercise():
        parent,link,pair,clock=await terminal_basis(submission_workflow);pair=dict(pair)
        extra=locked=''
        if change in ('tax','business'):
            name='skattemeldingUpersonligEtterBeregning' if change=='tax' else 'naeringsspesifikasjonEtterBeregning'
            pair[name]+=b'\n'
        elif change=='guidance':extra='<utvidetVeiledningdokument><id>new</id><encoding>utf-8</encoding><content>eA==</content></utvidetVeiledningdokument>'
        elif change=='locked':locked='<laasteFelt><laastFeltSkattemelding><sti>unknown</sti></laastFeltSkattemelding></laasteFelt>'
        with pytest.raises(CompanyTaxError):PinnedTax2025Schemas().inspect_current(current_pair(parent,pair,clock[0],extra=extra,locked=locked),
            **({} if change=='no-context' else {'correction_parent':link}))
    asyncio.run(exercise())


@pytest.mark.parametrize('change',['fork','missing-parent','unrelated','cycle'])
def test_complete_lineage_rejects_forks_missing_parents_and_unrelated_effects(submission_workflow,change):
    async def exercise():
        parent,link,pair,clock=await terminal_basis(submission_workflow);child=child_draft(parent,link,pair,clock[0])
        candidate=TaxDeliveryJournal(child,(),True,True,True,True,True,True)
        rows=[parent,candidate]
        if change=='fork':rows.append(TaxDeliveryJournal(replace(child,filing_id=str(uuid4())),(),True,True,True,True,True,True))
        elif change=='missing-parent':rows.remove(parent)
        elif change=='unrelated':
            other=replace(parent.draft,filing_id=str(uuid4()))
            approval=replace(parent.approval,filing_id=other.filing_id,draft_sha256=other.sha256)
            rows[1]=TaxDeliveryJournal(other,(replace(parent.events[0],value=approval),),True,True,True,True,True,True)
        else:
            # A self-parent cannot even be represented, before graph traversal.
            with pytest.raises(ValueError):replace(child,filing_id=link.filing_id)
            return
        with pytest.raises(ValueError):tax_delivery_lineage(tuple(rows))
    asyncio.run(exercise())


@pytest.mark.parametrize('change',['none','expired','scope','parent','budget'])
def test_separate_parent_reader_is_finite_known_scope_get_only(submission_workflow,change):
    async def exercise():
        parent,link,_,clock=await terminal_basis(submission_workflow);actor=parent.draft.prepared_by
        scope=TaxCurrentIntakeRehearsalAdmission(str(uuid4()),parent.draft.envelope.source.company_id,parent.draft.envelope.source.income_year,
            actor,parent.draft.envelope.source.organization_number,clock[0],Timestamp(clock[0].value+timedelta(minutes=5)),
            'http://127.0.0.1:41235','a'*64,'b'*64,3)
        admission=TaxParentReadRehearsalAdmission(scope,parent.draft.filing_id,parent.draft.sha256,parent.approval.sha256,link.terminal.instance.instance_id)
        runtime=TaxParentReadRehearsalRuntime(admission,now=lambda:clock[0]);calls=[]
        originals={link.terminal.instance.instance_id:link.terminal.instance.original,
            link.terminal.instance.instance_id+'/data/'+link.terminal.feedback.data_id:link.terminal.feedback.original,
            link.terminal.instance.instance_id+'/data/'+link.terminal.envelope.data_id:link.terminal.envelope.original}
        def wire(request):
            calls.append(request)
            assert request.method=='GET' and request.headers['X-Talli-Parent-Key']=='a'*64
            assert 'authorization' not in request.headers and 'X-Talli-Rehearsal-Key' not in request.headers
            original=originals[request.url.path.split('/instances/')[1]]
            return httpx.Response(200,content=original.raw_bytes,headers={'content-type':original.content_type})
        adapter=LoopbackCompanyTaxParentRead(runtime,transport=httpx.MockTransport(wire))
        query=TaxCurrentDocumentIntakeQuery(scope.company_id,scope.income_year,actor,scope.organization_number,'b'*64,CorrelationId('parent-read'))
        if change=='expired':clock[0]=scope.expires_at
        elif change=='scope':query=replace(query,database_scope_sha256='c'*64)
        elif change=='parent':runtime=TaxParentReadRehearsalRuntime(replace(admission,approval_sha256='d'*64),now=lambda:clock[0]);adapter=LoopbackCompanyTaxParentRead(runtime,transport=httpx.MockTransport(wire))
        if change in ('expired','scope','parent'):
            with pytest.raises(CompanyTaxError):await adapter.read_parent_instance(query,parent)
            assert not calls;return
        instance=await adapter.read_parent_instance(query,parent)
        feedback=await adapter.read_parent_feedback(query,parent,instance)
        envelope=await adapter.read_parent_envelope(query,parent,instance)
        assert feedback.original.raw_bytes==link.terminal.feedback.original.raw_bytes
        assert envelope.original.raw_bytes==parent.draft.envelope.envelope_xml.encode()
        assert len(calls)==3 and not hasattr(adapter,'execute') and not hasattr(adapter,'confirm_submission')
        with pytest.raises(CompanyTaxError):await adapter.read_parent_instance(query,parent)
        assert len(calls)==3
    asyncio.run(exercise())
