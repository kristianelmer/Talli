"""Finite backend-owned admission for one synthetic loopback Tax delivery.

This is technical rehearsal authority, issued only by trusted composition. It
is never accepted from an HTTP command and grants no Annual/Billing/live filing
authority. There is no production origin, credential lookup or environment flag.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass,field
from datetime import UTC,datetime
import hashlib
import json
import re
from urllib.parse import urlsplit
from uuid import UUID

from talli_backend.modules.company_tax_filing.public import CompanyTaxError,TaxDeliveryDraft,tax_delivery_digest
from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,IncomeYear,Timestamp,UserId


def loopback_tax_database_scope(host,port,database,user) -> str | None:
    """Nonsecret identity of an explicit restricted local rehearsal connector."""
    if (host!='127.0.0.1' or type(port) is not int or not 1024<=port<=65535
            or type(database) is not str or re.fullmatch('[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}',database) is None
            or type(user) is not str or re.fullmatch('[a-z_][a-z0-9_]{0,62}',user) is None
            or user in ('postgres','supabase_admin','supabase_auth_admin','supabase_storage_admin')):
        return None
    return tax_delivery_digest({'version':'tax-loopback-database-v1','host':host,'port':port,'database':database,'user':user})


def _loopback_origin(value):
    if type(value) is not str:raise ValueError('Finite Tax loopback origin is invalid.')
    origin=urlsplit(value)
    if (origin.scheme!='http' or origin.hostname!='127.0.0.1' or origin.port is None
            or not 1024<=origin.port<=65535 or value!='http://127.0.0.1:'+str(origin.port)):
        raise ValueError('Finite Tax loopback origin is invalid.')
    return value


@dataclass(frozen=True,slots=True)
class TaxDeliveryRehearsalAdmission:
    run_id: str
    company_id: CompanyId
    income_year: IncomeYear
    actor_id: ActorId
    filing_id: str
    draft_sha256: str
    organization_number: str
    issued_at: Timestamp
    expires_at: Timestamp
    origin: str
    credential: str=field(repr=False)
    database_scope_sha256: str
    maximum_requests: int=100

    def __post_init__(self):
        try:
            if (type(self.run_id) is not str or str(UUID(self.run_id))!=self.run_id
                    or type(self.filing_id) is not str or str(UUID(self.filing_id))!=self.filing_id
                    or type(self.company_id) is not CompanyId or type(self.income_year) is not IncomeYear
                    or type(self.income_year.value) is not int or int(self.income_year)!=2025
                    or type(self.actor_id) is not ActorId or self.actor_id.kind is not ActorKind.USER
                    or type(self.actor_id.subject) is not UserId or type(self.draft_sha256) is not str
                    or re.fullmatch('[0-9a-f]{64}',self.draft_sha256) is None
                    or type(self.organization_number) is not str or re.fullmatch('[0-9]{9}',self.organization_number) is None
                    or type(self.issued_at) is not Timestamp or type(self.expires_at) is not Timestamp
                    or not 0<(self.expires_at.value-self.issued_at.value).total_seconds()<=3600
                    or type(self.maximum_requests) is not int or not 1<=self.maximum_requests<=1000
                    or type(self.credential) is not str or re.fullmatch('[0-9a-f]{64}',self.credential) is None
                    or type(self.database_scope_sha256) is not str or re.fullmatch('[0-9a-f]{64}',self.database_scope_sha256) is None
                    or type(self.origin) is not str):
                raise ValueError()
            _loopback_origin(self.origin)
        except (ValueError,TypeError,AttributeError):
            raise ValueError('Tax rehearsal admission is invalid.') from None

    @property
    def canonical_context(self) -> str:
        """Retain the exact nonsecret context that the immutable review names."""
        return json.dumps({'version':'tax-loopback-admission-v1','runId':self.run_id,
            'companyId':str(self.company_id),'incomeYear':int(self.income_year),'actorId':str(self.actor_id.subject),
            'filingId':self.filing_id,'draftSha256':self.draft_sha256,'organizationNumber':self.organization_number,
            'issuedAt':self.issued_at.value.isoformat(),'expiresAt':self.expires_at.value.isoformat(),'origin':self.origin,
            'credentialSha256':hashlib.sha256(self.credential.encode('ascii')).hexdigest(),
            'databaseScopeSha256':self.database_scope_sha256,
            'maximumRequests':self.maximum_requests},sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)

    @property
    def context_sha256(self) -> str:
        return hashlib.sha256(self.canonical_context.encode('utf-8')).hexdigest()


class TaxDeliveryRehearsalRuntime:
    """One finite run; durable journal election remains the mutation authority."""
    def __init__(self,admission: TaxDeliveryRehearsalAdmission,*,now: Callable[[],Timestamp] | None=None):
        if type(admission) is not TaxDeliveryRehearsalAdmission:raise ValueError('Tax rehearsal admission is required.')
        self.admission=admission
        self._now=now or (lambda:Timestamp(datetime.now(UTC)))
        self._requests=0

    def now(self) -> Timestamp:
        value=self._now()
        if type(value) is not Timestamp:raise CompanyTaxError.unavailable()
        return value

    def assert_live(self) -> None:
        current=self.now().value
        if (not self.admission.issued_at.value<=current<self.admission.expires_at.value
                or self._requests>=self.admission.maximum_requests):
            raise CompanyTaxError.unavailable()

    def authorize(self,draft: TaxDeliveryDraft,actor_id: ActorId) -> str:
        grant=self.admission
        if actor_id!=grant.actor_id:raise CompanyTaxError.forbidden()
        if (type(draft) is not TaxDeliveryDraft or draft.current_document is None
                or draft.filing_id!=grant.filing_id or draft.sha256!=grant.draft_sha256
                or draft.envelope.source.company_id!=grant.company_id
                or draft.envelope.source.income_year!=grant.income_year
                or draft.envelope.source.organization_number!=grant.organization_number):
            raise CompanyTaxError.draft_conflict()
        self.assert_live()
        return grant.context_sha256

    def assert_session(self,session) -> None:
        if getattr(session,'delivery_rehearsal_target',None)!=self.admission.database_scope_sha256:
            raise CompanyTaxError.unavailable()

    def consume(self,*,organization_number: str,income_year: int) -> None:
        if (organization_number!=self.admission.organization_number or type(income_year) is not int
                or income_year!=int(self.admission.income_year)):
            raise CompanyTaxError.forbidden()
        self.assert_live()
        self._requests+=1

    @property
    def requests_used(self) -> int:
        return self._requests
