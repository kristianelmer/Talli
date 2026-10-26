"""Only metadata and its two known file GETs; no mutation or current lookup."""
import base64

from talli_backend.application.company_tax_parent_read_rehearsal import TaxParentReadRehearsalRuntime
from talli_backend.adapters.company_tax_loopback_read import read_tax_loopback_original
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxTerminalParentReader,company_tax_authority_adapter,CompanyTaxError,
    TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose,TaxDeliveryInstanceObservation,
    TaxDeliveryFeedbackObservation,TaxDeliveryEnvelopeObservation,
)

_PATH='/skd/formueinntekt-skattemelding-v2/instances/'


@company_tax_authority_adapter(CompanyTaxTerminalParentReader)
class LoopbackCompanyTaxParentRead:
    def __init__(self,runtime: TaxParentReadRehearsalRuntime,*,transport=None):
        if type(runtime) is not TaxParentReadRehearsalRuntime:raise ValueError('Finite parent read runtime is required.')
        self._runtime=runtime;self._transport=transport

    def available(self,query,journal) -> bool:
        return self._runtime.available(query,journal)

    async def _read(self,query,journal,path,purpose):
        self._runtime.consume(query,journal);grant=self._runtime.admission.scope
        raw,media=await read_tax_loopback_original(grant.origin,path,
            {'X-Talli-Parent-Run':grant.run_id,'X-Talli-Parent-Key':grant.credential},
            ('application/json',) if purpose is TaxDeliveryOriginalPurpose.INSTANCE else ('application/xml','text/xml'),
            transport=self._transport)
        return TaxDeliveryReadOriginal(purpose,base64.b64encode(raw).decode('ascii'),media,200)

    async def read_parent_instance(self,query,journal):
        approval=journal.approval;draft=journal.draft;identity=self._runtime.admission.instance_id
        original=await self._read(query,journal,_PATH+identity,TaxDeliveryOriginalPurpose.INSTANCE)
        value=TaxDeliveryInstanceObservation(draft.filing_id,query.company_id,query.income_year,query.actor_id,
            approval.sha256,query.organization_number,identity,original,self._runtime.now())
        value.assert_approval(approval,draft,identity)
        return value

    async def read_parent_feedback(self,query,journal,instance):
        return await self._file(query,journal,instance,TaxDeliveryOriginalPurpose.FEEDBACK)

    async def read_parent_envelope(self,query,journal,instance):
        return await self._file(query,journal,instance,TaxDeliveryOriginalPurpose.ENVELOPE)

    async def _file(self,query,journal,instance,purpose):
        approval=journal.approval;draft=journal.draft
        instance.assert_approval(approval,draft,self._runtime.admission.instance_id)
        info=instance.inspection
        element=info.feedback if purpose is TaxDeliveryOriginalPurpose.FEEDBACK else info.envelope
        if (not info.known or info.process_task is not None or info.process_ended_at is None
                or info.archived is not True or info.archived_at is None or element is None
                or element.scan_result!='Clean' or element.content_type.split(';',1)[0].strip().lower() not in ('application/xml','text/xml')):
            raise CompanyTaxError.unavailable()
        original=await self._read(query,journal,_PATH+instance.instance_id+'/data/'+element.data_id,purpose)
        kind=TaxDeliveryFeedbackObservation if purpose is TaxDeliveryOriginalPurpose.FEEDBACK else TaxDeliveryEnvelopeObservation
        value=kind(draft.filing_id,query.company_id,query.income_year,query.actor_id,approval.sha256,
            query.organization_number,instance.instance_id,element.data_id,instance.evidence_sha256,original,self._runtime.now())
        value.assert_instance(approval,draft,instance)
        return value
