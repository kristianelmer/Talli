"""One fixed current-document GET under separate finite read-only authority."""
import base64

from talli_backend.adapters.company_tax_loopback_read import read_tax_loopback_original

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
        raw,_=await read_tax_loopback_original(grant.origin,'/api/skattemelding/v2/2025/'+grant.organization_number,
            {'X-Talli-Intake-Run':grant.run_id,'X-Talli-Intake-Key':grant.credential},('application/xml','text/xml'),transport=self._transport)
        return TaxCurrentDocumentResponse(grant.organization_number,grant.income_year,
            base64.b64encode(raw).decode('ascii'),self._runtime.now())
