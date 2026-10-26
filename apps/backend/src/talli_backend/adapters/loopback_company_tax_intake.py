"""One fixed current-document GET under separate finite read-only authority."""
import asyncio
import base64

import httpx

from talli_backend.application.company_tax_intake_rehearsal import TaxCurrentIntakeRehearsalRuntime
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxCurrentDocumentIntake,TaxCurrentDocumentIntakeQuery,TaxCurrentDocumentResponse,
    CompanyTaxReturnAuthorityError,company_tax_authority_adapter,
)


@company_tax_authority_adapter(CompanyTaxCurrentDocumentIntake)
class LoopbackCompanyTaxIntake:
    def __init__(self,runtime: TaxCurrentIntakeRehearsalRuntime,*,transport=None):
        if type(runtime) is not TaxCurrentIntakeRehearsalRuntime:raise ValueError('Finite read-only intake runtime is required.')
        self._runtime=runtime;self._transport=transport

    async def read_current_document(self,query: TaxCurrentDocumentIntakeQuery) -> TaxCurrentDocumentResponse:
        self._runtime.consume(query);grant=self._runtime.admission
        try:
            async with asyncio.timeout(5):
                async with httpx.AsyncClient(base_url=grant.origin,timeout=5,follow_redirects=False,
                        trust_env=False,transport=self._transport) as client:
                    async with client.stream('GET','/api/skattemelding/v2/2025/'+grant.organization_number,
                            headers={'X-Talli-Intake-Run':grant.run_id,'X-Talli-Intake-Key':grant.credential}) as response:
                        if response.status_code!=200 or response.headers.get('content-type','').split(';',1)[0].strip().lower() not in ('application/xml','text/xml'):
                            raise ValueError()
                        chunks=[];size=0
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            size+=len(chunk)
                            if size>8*1024*1024:raise ValueError()
                            chunks.append(chunk)
                        raw=b''.join(chunks)
                        if not raw:raise ValueError()
            return TaxCurrentDocumentResponse(grant.organization_number,grant.income_year,
                base64.b64encode(raw).decode('ascii'),self._runtime.now())
        except (httpx.HTTPError,TimeoutError,ValueError,TypeError,UnicodeError):
            raise CompanyTaxReturnAuthorityError('Finite Tax intake response unavailable.',
                code='COMPANY_TAX_REHEARSAL_AUTHORITY_UNAVAILABLE') from None
