"""Separate short-lived read authority for one already-known parent instance."""
from dataclasses import dataclass
from uuid import UUID
import re

from talli_backend.application.company_tax_intake_rehearsal import TaxCurrentIntakeRehearsalAdmission,TaxCurrentIntakeRehearsalRuntime
from talli_backend.modules.company_tax_filing.public import CompanyTaxError,TaxMutationKind


@dataclass(frozen=True,slots=True)
class TaxParentReadRehearsalAdmission:
    scope: TaxCurrentIntakeRehearsalAdmission
    filing_id: str
    draft_sha256: str
    approval_sha256: str
    instance_id: str

    def __post_init__(self):
        if type(self.scope) is not TaxCurrentIntakeRehearsalAdmission:raise ValueError('Finite Tax parent read scope is required.')
        if (str(UUID(self.filing_id))!=self.filing_id or type(self.instance_id) is not str
                or re.fullmatch('[0-9]{1,19}/[0-9a-f-]{36}',self.instance_id) is None
                or str(UUID(self.instance_id.split('/')[1]))!=self.instance_id.split('/')[1]
                or any(type(value) is not str or re.fullmatch('[0-9a-f]{64}',value) is None
                    for value in (self.draft_sha256,self.approval_sha256))):raise ValueError('Tax parent read target is invalid.')


class TaxParentReadRehearsalRuntime:
    def __init__(self,admission: TaxParentReadRehearsalAdmission,*,now=None):
        if type(admission) is not TaxParentReadRehearsalAdmission:raise ValueError('Finite Tax parent read admission is required.')
        self.admission=admission
        self._budget=TaxCurrentIntakeRehearsalRuntime(admission.scope,now=now)

    def now(self):return self._budget.now()

    def consume(self,query,journal):
        grant=self.admission;approval=journal.approval
        created=next((e.value for e in journal.events if e.slot=='completion:create_instance'),None)
        submitted=next((e.value for e in journal.events if e.slot=='completion:confirm_submission'),None)
        if (journal.draft.filing_id!=grant.filing_id or journal.draft.sha256!=grant.draft_sha256
                or approval is None or approval.sha256!=grant.approval_sha256
                or approval.approved_by!=query.actor_id or created is None or submitted is None
                or submitted.intent.kind is not TaxMutationKind.CONFIRM_SUBMISSION
                or created.result['instanceId']!=grant.instance_id or submitted.result['instanceId']!=grant.instance_id):
            raise CompanyTaxError.forbidden()
        self._budget.consume(query)
