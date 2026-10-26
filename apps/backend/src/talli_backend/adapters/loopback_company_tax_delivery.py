"""Fixed-path Tax authority transport confined to one finite loopback run."""
from __future__ import annotations

import base64
import asyncio
from dataclasses import dataclass
import httpx

from talli_backend.application.company_tax_delivery_rehearsal import TaxDeliveryRehearsalRuntime
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,CompanyTaxReturnAuthorityError,TaxCurrentDocumentResponse,TaxDeliveryDraft,
    TaxDeliveryReviewApproval,TaxDeliveryMutationRequest,TaxDeliveryMutationCompletion,
    TaxMutationKind,TaxDeliveryCompletionOrigin,complete_tax_delivery_mutation,
    TaxDeliveryMutationAuthority,company_tax_authority_adapter,
    TaxDeliveryOriginalPurpose,TaxDeliveryReadOriginal,TaxDeliveryInstanceObservation,
    build_tax_delivery_mutation_request,
    TaxDeliveryEnvelopeObservation,
    TaxDeliveryValidationJobObservation,TaxDeliveryValidationResultObservation,TaxValidationJobStatus,
    TaxDeliveryProcessAcknowledgment,
)
from talli_backend.shared.kernel import IncomeYear

_APP_PATH='/skd/formueinntekt-skattemelding-v2'
_AUTHORITY_DEADLINE_SECONDS=5.0


@dataclass(frozen=True,slots=True)
class _AuthorityResponse:
    raw_bytes: bytes
    status: int
    media_type: str


@company_tax_authority_adapter(TaxDeliveryMutationAuthority)
class LoopbackCompanyTaxDelivery:
    def __init__(self,runtime: TaxDeliveryRehearsalRuntime,*,transport=None):
        if type(runtime) is not TaxDeliveryRehearsalRuntime:raise ValueError('Finite Tax runtime is required.')
        self._runtime=runtime
        self._transport=transport

    async def _request(self,method: str,path: str,*,body: bytes | None=None,content_type: str | None=None,
            content_disposition: str | None=None,expected_statuses=(200,201),response_types=()) -> _AuthorityResponse:
        grant=self._runtime.admission
        self._runtime.consume(organization_number=grant.organization_number,income_year=int(grant.income_year))
        headers={'X-Talli-Rehearsal-Run':grant.run_id,'X-Talli-Rehearsal-Key':grant.credential}
        if content_type is not None:headers['Content-Type']=content_type
        if content_disposition is not None:headers['Content-Disposition']=content_disposition
        try:
            async with asyncio.timeout(_AUTHORITY_DEADLINE_SECONDS):
                async with httpx.AsyncClient(base_url=grant.origin,timeout=5,follow_redirects=False,
                        trust_env=False,transport=self._transport) as client:
                    async with client.stream(method,path,content=body,headers=headers) as response:
                        if response.status_code not in expected_statuses:raise ValueError()
                        media_type=response.headers.get('content-type','').split(';',1)[0].strip().lower()
                        if response_types and media_type not in response_types:
                            raise ValueError()
                        chunks=[];size=0
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            size+=len(chunk)
                            if size>8*1024*1024:raise ValueError()
                            chunks.append(chunk)
                        raw=b''.join(chunks)
                        if not raw:raise ValueError()
                        return _AuthorityResponse(raw,response.status_code,media_type)
        except (httpx.HTTPError,TimeoutError,ValueError,UnicodeError):
            raise CompanyTaxReturnAuthorityError('Finite Tax authority response unavailable.',
                code='COMPANY_TAX_REHEARSAL_AUTHORITY_UNAVAILABLE') from None

    async def fetch_current_document(self,*,income_year: int,company_org_number: str) -> TaxCurrentDocumentResponse:
        grant=self._runtime.admission
        if type(income_year) is not int or income_year!=2025 or company_org_number!=grant.organization_number:
            raise CompanyTaxError.forbidden()
        response=await self._request('GET',f'/api/skattemelding/v2/{income_year}/{company_org_number}')
        return TaxCurrentDocumentResponse(company_org_number,IncomeYear(income_year),
            base64.b64encode(response.raw_bytes).decode('ascii'),self._runtime.now())

    async def execute(self,request: TaxDeliveryMutationRequest,approval: TaxDeliveryReviewApproval,
            draft: TaxDeliveryDraft) -> TaxDeliveryMutationCompletion:
        request.assert_draft(approval,draft)
        if self._runtime.authorize(draft,approval.approved_by)!=approval.authority_context_sha256:
            raise CompanyTaxError.forbidden()
        # The workflow elects the acknowledged committed intent. Upload adds a
        # bounded fresh prerequisite; no generic method/path escape is exposed.
        if request.kind is TaxMutationKind.CREATE_INSTANCE:
            response=await self._request('POST',_APP_PATH+'/instances/',body=request.body_bytes,content_type='application/json')
        elif request.kind is TaxMutationKind.UPLOAD_ENVELOPE:
            if request.upload_prerequisite is None:raise CompanyTaxError.unavailable()
            try:request.upload_prerequisite.assert_current(self._runtime.now())
            except ValueError:raise CompanyTaxError.unavailable() from None
            response=await self._request('POST',_APP_PATH+'/instances/'+request.target_instance+'/data?dataType=skattemeldingOgNaeringsspesifikasjon',
                body=request.body_bytes,content_type='text/xml',
                content_disposition='attachment; filename=skattemelding.xml',response_types=('application/json',))
        elif request.kind is TaxMutationKind.START_VALIDATION:
            if request.validation_prerequisite is None:raise CompanyTaxError.unavailable()
            try:request.validation_prerequisite.assert_current(self._runtime.now())
            except ValueError:raise CompanyTaxError.unavailable() from None
            response=await self._request('POST',f'/api/skattemelding/v2/jobb/altinn/{int(approval.income_year)}/'
                +draft.envelope.source.organization_number+'/start',body=request.body_bytes,content_type='application/json')
        else:raise CompanyTaxError.unavailable()
        try:
            return complete_tax_delivery_mutation(request,approval,draft,response_bytes=response.raw_bytes,
                observed_at=self._runtime.now(),origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)
        except (ValueError,TypeError,AttributeError,RecursionError,OverflowError):
            raise CompanyTaxReturnAuthorityError('Finite Tax mutation result is unknown.',
                code='COMPANY_TAX_REHEARSAL_AUTHORITY_UNAVAILABLE') from None

    async def prepare_confirmation(self,request: TaxDeliveryMutationRequest,approval: TaxDeliveryReviewApproval,
            draft: TaxDeliveryDraft) -> TaxDeliveryProcessAcknowledgment:
        request.assert_draft(approval,draft)
        if request.kind is not TaxMutationKind.PREPARE_CONFIRMATION or request.confirmation_prerequisite is None:
            raise CompanyTaxError.unavailable()
        if self._runtime.authorize(draft,approval.approved_by)!=approval.authority_context_sha256:raise CompanyTaxError.forbidden()
        try:request.confirmation_prerequisite.assert_current(self._runtime.now())
        except ValueError:raise CompanyTaxError.unavailable() from None
        response=await self._request('PUT',_APP_PATH+'/instances/'+request.target_instance+'/process/next',
            body=request.body_bytes,content_type='application/json',expected_statuses=(200,),response_types=('application/json',))
        try:
            result=TaxDeliveryProcessAcknowledgment(draft.filing_id,approval.company_id,approval.income_year,approval.approved_by,
                approval.sha256,draft.envelope.source.organization_number,request.target_instance,request.sha256,
                TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.PROCESS_RESPONSE,base64.b64encode(response.raw_bytes).decode('ascii'),
                    response.media_type,response.status),self._runtime.now())
            result.assert_request(request,approval,draft)
            return result
        except (ValueError,TypeError,AttributeError,RecursionError,OverflowError):
            raise CompanyTaxReturnAuthorityError('Finite Tax process acknowledgment is unknown.',
                code='COMPANY_TAX_REHEARSAL_AUTHORITY_UNAVAILABLE') from None

    async def observe_instance(self,approval: TaxDeliveryReviewApproval,draft: TaxDeliveryDraft,
            created: TaxDeliveryMutationCompletion) -> TaxDeliveryInstanceObservation:
        # Only a retained, draft-bound create result can supply a read target.
        if type(created) is not TaxDeliveryMutationCompletion or created.intent.kind is not TaxMutationKind.CREATE_INSTANCE:
            raise CompanyTaxError.invalid_input()
        created.assert_request(build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.CREATE_INSTANCE),approval)
        if self._runtime.authorize(draft,approval.approved_by)!=approval.authority_context_sha256:raise CompanyTaxError.forbidden()
        instance=created.result['instanceId']
        response=await self._request('GET',_APP_PATH+'/instances/'+instance,expected_statuses=(200,),response_types=('application/json',))
        try:
            value=TaxDeliveryInstanceObservation(draft.filing_id,approval.company_id,approval.income_year,
                approval.approved_by,approval.sha256,draft.envelope.source.organization_number,instance,
                TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.INSTANCE,base64.b64encode(response.raw_bytes).decode('ascii'),response.media_type,response.status),
                self._runtime.now())
            value.assert_approval(approval,draft,instance)
            return value
        except (ValueError,TypeError,AttributeError,RecursionError,OverflowError):
            raise CompanyTaxReturnAuthorityError('Finite Tax instance scope is unavailable.',
                code='COMPANY_TAX_REHEARSAL_AUTHORITY_UNAVAILABLE') from None

    async def observe_envelope(self,approval: TaxDeliveryReviewApproval,draft: TaxDeliveryDraft,
            created: TaxDeliveryMutationCompletion,instance: TaxDeliveryInstanceObservation) -> TaxDeliveryEnvelopeObservation:
        if (type(created) is not TaxDeliveryMutationCompletion or created.intent.kind is not TaxMutationKind.CREATE_INSTANCE
                or type(instance) is not TaxDeliveryInstanceObservation):raise CompanyTaxError.invalid_input()
        created.assert_request(build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.CREATE_INSTANCE),approval)
        instance.assert_approval(approval,draft,created.result['instanceId'])
        element=instance.inspection.envelope
        if (not instance.inspection.known or element is None
                or element.content_type.split(';',1)[0].strip().lower() not in ('application/xml','text/xml')):
            raise CompanyTaxError.unavailable()
        if self._runtime.authorize(draft,approval.approved_by)!=approval.authority_context_sha256:raise CompanyTaxError.forbidden()
        response=await self._request('GET',_APP_PATH+'/instances/'+instance.instance_id+'/data/'+element.data_id,
            expected_statuses=(200,),response_types=('application/xml','text/xml'))
        try:
            value=TaxDeliveryEnvelopeObservation(draft.filing_id,approval.company_id,approval.income_year,
                approval.approved_by,approval.sha256,draft.envelope.source.organization_number,instance.instance_id,
                element.data_id,instance.evidence_sha256,TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.ENVELOPE,
                    base64.b64encode(response.raw_bytes).decode('ascii'),response.media_type,response.status),self._runtime.now())
            value.assert_instance(approval,draft,instance)
            return value
        except (ValueError,TypeError,AttributeError,RecursionError,OverflowError):
            raise CompanyTaxReturnAuthorityError('Finite Tax envelope scope is unavailable.',
                code='COMPANY_TAX_REHEARSAL_AUTHORITY_UNAVAILABLE') from None

    async def observe_validation_job(self,approval: TaxDeliveryReviewApproval,draft: TaxDeliveryDraft,
            request: TaxDeliveryMutationRequest,started: TaxDeliveryMutationCompletion) -> TaxDeliveryValidationJobObservation:
        if (type(request) is not TaxDeliveryMutationRequest or request.kind is not TaxMutationKind.START_VALIDATION
                or type(started) is not TaxDeliveryMutationCompletion):raise CompanyTaxError.invalid_input()
        request.assert_draft(approval,draft);started.assert_request(request,approval)
        if self._runtime.authorize(draft,approval.approved_by)!=approval.authority_context_sha256:raise CompanyTaxError.forbidden()
        response=await self._request('GET',f'/api/skattemelding/v2/jobb/altinn/{int(approval.income_year)}/'
            +draft.envelope.source.organization_number+'/'+started.result['jobId']+'/status',
            expected_statuses=(200,),response_types=('application/json',))
        try:
            value=TaxDeliveryValidationJobObservation(draft.filing_id,approval.company_id,approval.income_year,
                approval.approved_by,approval.sha256,draft.envelope.source.organization_number,started.result['instanceId'],
                started.result['jobId'],request.sha256,TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.VALIDATION_JOB,
                    base64.b64encode(response.raw_bytes).decode('ascii'),response.media_type,response.status),self._runtime.now())
            value.assert_started(approval,draft,request,started)
            return value
        except (ValueError,TypeError,AttributeError,RecursionError,OverflowError):
            raise CompanyTaxReturnAuthorityError('Finite Tax validation job scope is unavailable.',
                code='COMPANY_TAX_REHEARSAL_AUTHORITY_UNAVAILABLE') from None

    async def observe_validation_result(self,approval: TaxDeliveryReviewApproval,draft: TaxDeliveryDraft,
            request: TaxDeliveryMutationRequest,started: TaxDeliveryMutationCompletion,
            status: TaxDeliveryValidationJobObservation,*,schema_sha256: str) -> TaxDeliveryValidationResultObservation:
        if type(status) is not TaxDeliveryValidationJobObservation:raise CompanyTaxError.invalid_input()
        status.assert_started(approval,draft,request,started)
        if not status.inspection.known or status.inspection.status is not TaxValidationJobStatus.FINISHED:
            raise CompanyTaxError.unavailable()
        if self._runtime.authorize(draft,approval.approved_by)!=approval.authority_context_sha256:raise CompanyTaxError.forbidden()
        response=await self._request('GET',f'/api/skattemelding/v2/jobb/altinn/{int(approval.income_year)}/'
            +draft.envelope.source.organization_number+'/'+started.result['jobId']+'/resultat',
            expected_statuses=(200,),response_types=('application/xml','text/xml'))
        try:
            value=TaxDeliveryValidationResultObservation(draft.filing_id,approval.company_id,approval.income_year,
                approval.approved_by,approval.sha256,draft.envelope.source.organization_number,started.result['instanceId'],
                started.result['jobId'],request.sha256,status.evidence_sha256,schema_sha256,
                TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.VALIDATION_RESULT,
                    base64.b64encode(response.raw_bytes).decode('ascii'),response.media_type,response.status),self._runtime.now())
            value.assert_status(approval,draft,request,started,status)
            return value
        except (ValueError,TypeError,AttributeError,RecursionError,OverflowError):
            raise CompanyTaxReturnAuthorityError('Finite Tax validation result scope is unavailable.',
                code='COMPANY_TAX_REHEARSAL_AUTHORITY_UNAVAILABLE') from None
