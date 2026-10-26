"""Fixed-path Tax authority transport confined to one finite loopback run."""
from __future__ import annotations

import base64
import asyncio
import httpx

from talli_backend.application.company_tax_delivery_rehearsal import TaxDeliveryRehearsalRuntime
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,CompanyTaxReturnAuthorityError,TaxCurrentDocumentResponse,TaxDeliveryDraft,
    TaxDeliveryReviewApproval,TaxDeliveryMutationRequest,TaxDeliveryMutationCompletion,
    TaxMutationKind,TaxDeliveryCompletionOrigin,complete_tax_delivery_mutation,
    TaxDeliveryMutationAuthority,company_tax_authority_adapter,
)
from talli_backend.shared.kernel import IncomeYear

_APP_PATH='/skd/formueinntekt-skattemelding-v2'
_AUTHORITY_DEADLINE_SECONDS=5.0


@company_tax_authority_adapter(TaxDeliveryMutationAuthority)
class LoopbackCompanyTaxDelivery:
    def __init__(self,runtime: TaxDeliveryRehearsalRuntime,*,transport=None):
        if type(runtime) is not TaxDeliveryRehearsalRuntime:raise ValueError('Finite Tax runtime is required.')
        self._runtime=runtime
        self._transport=transport

    async def _request(self,method: str,path: str,*,body: bytes | None=None,content_type: str | None=None) -> bytes:
        grant=self._runtime.admission
        self._runtime.consume(organization_number=grant.organization_number,income_year=int(grant.income_year))
        headers={'X-Talli-Rehearsal-Run':grant.run_id,'X-Talli-Rehearsal-Key':grant.credential}
        if content_type is not None:headers['Content-Type']=content_type
        try:
            async with asyncio.timeout(_AUTHORITY_DEADLINE_SECONDS):
                async with httpx.AsyncClient(base_url=grant.origin,timeout=5,follow_redirects=False,
                        trust_env=False,transport=self._transport) as client:
                    async with client.stream(method,path,content=body,headers=headers) as response:
                        if response.status_code not in (200,201):raise ValueError()
                        chunks=[];size=0
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            size+=len(chunk)
                            if size>8*1024*1024:raise ValueError()
                            chunks.append(chunk)
                        raw=b''.join(chunks)
                        if not raw:raise ValueError()
                        return raw
        except (httpx.HTTPError,TimeoutError,ValueError,UnicodeError):
            raise CompanyTaxReturnAuthorityError('Finite Tax authority response unavailable.',
                code='COMPANY_TAX_REHEARSAL_AUTHORITY_UNAVAILABLE') from None

    async def fetch_current_document(self,*,income_year: int,company_org_number: str) -> TaxCurrentDocumentResponse:
        grant=self._runtime.admission
        if type(income_year) is not int or income_year!=2025 or company_org_number!=grant.organization_number:
            raise CompanyTaxError.forbidden()
        raw=await self._request('GET',f'/api/skattemelding/v2/{income_year}/{company_org_number}')
        return TaxCurrentDocumentResponse(company_org_number,IncomeYear(income_year),
            base64.b64encode(raw).decode('ascii'),self._runtime.now())

    async def execute(self,request: TaxDeliveryMutationRequest,approval: TaxDeliveryReviewApproval,
            draft: TaxDeliveryDraft) -> TaxDeliveryMutationCompletion:
        request.assert_draft(approval,draft)
        if self._runtime.authorize(draft,approval.approved_by)!=approval.authority_context_sha256:
            raise CompanyTaxError.forbidden()
        # Later mutations stay closed until their retained read prerequisites
        # and recovery proofs are implemented. No generic method/path escape.
        if request.kind is not TaxMutationKind.CREATE_INSTANCE:raise CompanyTaxError.unavailable()
        raw=await self._request('POST',_APP_PATH+'/instances/',body=request.body_bytes,content_type='application/json')
        try:
            return complete_tax_delivery_mutation(request,approval,draft,response_bytes=raw,
                observed_at=self._runtime.now(),origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)
        except (ValueError,TypeError,AttributeError,RecursionError,OverflowError):
            raise CompanyTaxReturnAuthorityError('Finite Tax mutation result is unknown.',
                code='COMPANY_TAX_REHEARSAL_AUTHORITY_UNAVAILABLE') from None
