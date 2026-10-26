"""Finite read-only loopback admission before an immutable Tax draft exists.

No filing identifier or placeholder draft hash is an authorization input. The
separate delivery admission can be issued only after the exact draft is known.
"""
from dataclasses import dataclass,field
from datetime import datetime,UTC
import hashlib
import json
import re
from threading import Lock
from uuid import UUID

from talli_backend.application.company_tax_delivery_rehearsal import _loopback_origin
from talli_backend.modules.company_tax_filing.public import CompanyTaxError,TaxCurrentDocumentIntakeQuery
from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,IncomeYear,Timestamp,UserId


@dataclass(frozen=True,slots=True)
class TaxCurrentIntakeRehearsalAdmission:
    run_id: str
    company_id: CompanyId
    income_year: IncomeYear
    actor_id: ActorId
    organization_number: str
    issued_at: Timestamp
    expires_at: Timestamp
    origin: str
    credential: str=field(repr=False)
    database_scope_sha256: str
    maximum_requests: int=2

    def __post_init__(self):
        try:
            if (type(self.run_id) is not str or str(UUID(self.run_id))!=self.run_id
                    or type(self.company_id) is not CompanyId or type(self.income_year) is not IncomeYear
                    or type(self.income_year.value) is not int or int(self.income_year)!=2025
                    or type(self.actor_id) is not ActorId or self.actor_id.kind is not ActorKind.USER
                    or type(self.actor_id.subject) is not UserId
                    or type(self.organization_number) is not str or re.fullmatch('[0-9]{9}',self.organization_number) is None
                    or type(self.issued_at) is not Timestamp or type(self.expires_at) is not Timestamp
                    or not 0<(self.expires_at.value-self.issued_at.value).total_seconds()<=300
                    or type(self.maximum_requests) is not int or not 1<=self.maximum_requests<=4
                    or type(self.credential) is not str or re.fullmatch('[0-9a-f]{64}',self.credential) is None
                    or type(self.database_scope_sha256) is not str or re.fullmatch('[0-9a-f]{64}',self.database_scope_sha256) is None):
                raise ValueError()
            _loopback_origin(self.origin)
        except (ValueError,TypeError,AttributeError):
            raise ValueError('Tax read-only intake admission is invalid.') from None

    @property
    def canonical_context(self):
        return json.dumps({'version':'tax-loopback-current-intake-v1','runId':self.run_id,
            'companyId':str(self.company_id),'incomeYear':int(self.income_year),'actorId':str(self.actor_id.subject),
            'organizationNumber':self.organization_number,'issuedAt':self.issued_at.value.isoformat(),
            'expiresAt':self.expires_at.value.isoformat(),'origin':self.origin,
            'credentialSha256':hashlib.sha256(self.credential.encode('ascii')).hexdigest(),
            'databaseScopeSha256':self.database_scope_sha256,'maximumRequests':self.maximum_requests},
            sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)

    @property
    def context_sha256(self):return hashlib.sha256(self.canonical_context.encode('utf-8')).hexdigest()


class TaxCurrentIntakeRehearsalRuntime:
    def __init__(self,admission: TaxCurrentIntakeRehearsalAdmission,*,now=None):
        if type(admission) is not TaxCurrentIntakeRehearsalAdmission:raise ValueError('Finite read-only intake admission is required.')
        self.admission=admission;self._now=now or (lambda:Timestamp(datetime.now(UTC)))
        self._requests=0;self._lock=Lock()

    def now(self):
        value=self._now()
        if type(value) is not Timestamp:raise CompanyTaxError.unavailable()
        return value

    def _assert_scope(self,query: TaxCurrentDocumentIntakeQuery):
        grant=self.admission
        if type(query) is not TaxCurrentDocumentIntakeQuery:raise CompanyTaxError.invalid_input()
        if (query.company_id!=grant.company_id or query.income_year!=grant.income_year or query.actor_id!=grant.actor_id
                or query.organization_number!=grant.organization_number or query.database_scope_sha256!=grant.database_scope_sha256):
            raise CompanyTaxError.forbidden()
    def consume(self,query: TaxCurrentDocumentIntakeQuery):
        self._assert_scope(query)
        with self._lock:
            self._assert_live()
            self._requests+=1

    def _assert_live(self):
        grant=self.admission
        if not grant.issued_at.value<=self.now().value<grant.expires_at.value or self._requests>=grant.maximum_requests:
            raise CompanyTaxError.unavailable()

    def available(self,query: TaxCurrentDocumentIntakeQuery) -> bool:
        try:
            self._assert_scope(query)
            with self._lock:self._assert_live()
        except CompanyTaxError:return False
        return True
