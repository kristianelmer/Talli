"""Trusted, finite Accounts rehearsal composition. No live-provider fallback."""
from collections.abc import Callable
from dataclasses import dataclass,field
from datetime import UTC,datetime,timedelta
import hashlib
import re
from threading import Lock
from uuid import uuid4

from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsError,AnnualAccountsFiniteAdmission as Admission,AnnualAccountsAuthorityPort as Port,
    AnnualAccountsDeliveryStage as Stage,AnnualAccountsDeliveryBinding as Binding,annual_accounts_delivery_digest,
)
from talli_backend.shared.kernel import Timestamp


def loopback_accounts_database_scope(host,port,database,user):
    """Nonsecret identity; administrative or hosted connectors have no scope."""
    if (host!='127.0.0.1' or type(port) is not int or not 1024<=port<=65535
            or type(database) is not str or re.fullmatch('[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}',database) is None
            or type(user) is not str or re.fullmatch('[a-z_][a-z0-9_]{0,62}',user) is None
            or user in ('postgres','supabase_admin','supabase_auth_admin','supabase_storage_admin')):return None
    return annual_accounts_delivery_digest({'version':'accounts-loopback-database-v1','host':host,
        'port':port,'database':database,'user':user})


@dataclass(frozen=True,slots=True)
class AccountsRehearsalCredential:
    admission: Admission
    credential: str=field(repr=False)

    def __post_init__(self):
        if (type(self.admission) is not Admission or type(self.credential) is not str
                or re.fullmatch('[0-9a-f]{64}',self.credential) is None
                or hashlib.sha256(self.credential.encode()).hexdigest()!=self.admission.credential_sha256):raise ValueError()


class AccountsRehearsalRuntime:
    def __init__(self,credential,*,now=None):
        if type(credential) is not AccountsRehearsalCredential:raise ValueError()
        self._credential=credential;self._now=now or (lambda:Timestamp(datetime.now(UTC)))
        self._lock=Lock();self._used=0

    @property
    def admission(self):return self._credential.admission

    def now(self):
        value=self._now()
        if type(value) is not Timestamp:raise AnnualAccountsError.unavailable()
        return value

    def assert_session(self,session):
        if (session.actor_id!=self.admission.binding.actor_id
                or getattr(session,'delivery_rehearsal_target',None)!=self.admission.database_scope_sha256):
            raise AnnualAccountsError.forbidden()

    def assert_available(self):
        with self._lock:
            try:self.admission.assert_current(self.now())
            except ValueError:raise AnnualAccountsError.unavailable() from None
            if self._used>=self.admission.maximum_requests:raise AnnualAccountsError.unavailable()

    def request_headers(self):
        # Atomic across concurrent users of the same grant. SQL separately
        # counts the retained request graph; no renewed budget on replay.
        with self._lock:
            try:self.admission.assert_current(self.now())
            except ValueError:raise AnnualAccountsError.unavailable() from None
            if self._used>=self.admission.maximum_requests:raise AnnualAccountsError.unavailable()
            self._used+=1
            return {'X-Talli-Rehearsal-Run':self.admission.run_id,
                'X-Talli-Rehearsal-Key':self._credential.credential}

    @property
    def requests_used(self):
        with self._lock:return self._used

    @property
    def requests_remaining(self):
        with self._lock:return self.admission.maximum_requests-self._used


class AccountsRehearsalPorts:
    """One trusted owner/company/run, bounded child grants issued after commits.

    The backend's default composition has no instance of this class. The owned
    fixture passes distinct credentials and constructors for each role. A lost
    process cannot reconstruct or renew a retained grant from its public hash.
    """
    def __init__(self,*,company_id,income_year,actor_id,organization_number,origin,database_scope_sha256,
            credentials,builders,expires_at,now=None,maximum_filings=2):
        self._company,self._year,self._actor=company_id,income_year,actor_id
        self._organization,self._origin,self._database=organization_number,origin,database_scope_sha256
        self._credentials=dict(credentials);self._builders=dict(builders);self._expires=expires_at
        self._now=now or (lambda:Timestamp(datetime.now(UTC)));self._ports={};self._lock=Lock()
        self._run=str(uuid4());self._maximum_filings=maximum_filings
        keys={(Port.SYSTEM_USER,Stage.PREPARE),(Port.SYSTEM_USER,Stage.CONFIRM),(Port.PERSON,Stage.SIGN),(Port.KNOWN_READ,None)}
        if (set(self._credentials)!=keys or set(self._builders)!=keys
                or len(set(self._credentials.values()))!=4 or type(maximum_filings) is not int or not 1<=maximum_filings<=2
                or type(expires_at) is not Timestamp or not 0<(expires_at.value-self.now().value).total_seconds()<=3600):raise ValueError()

    def now(self):return self._now()

    def available(self,session,company_id,income_year):
        """Non-consuming composition hint; SQL and source still decide at use."""
        return (session.actor_id==self._actor and company_id==self._company and income_year==self._year
            and getattr(session,'delivery_rehearsal_target',None)==self._database and self.now().value<self._expires.value)

    def stage_available(self,session,draft,stage):
        if not self.available(session,draft.source.company_id,draft.source.income_year):return False
        role=Port.PERSON if stage is Stage.SIGN else Port.SYSTEM_USER
        with self._lock:port=self._ports.get((draft.filing_id,role,stage))
        if port is None:return True
        try:port.runtime.assert_available();return True
        except AnnualAccountsError:return False

    def _scope(self,session,draft):
        if (session.actor_id!=self._actor or draft.prepared_by!=self._actor or draft.source.company_id!=self._company
                or draft.source.income_year!=self._year or draft.source.organization_number!=self._organization
                or getattr(session,'delivery_rehearsal_target',None)!=self._database):raise AnnualAccountsError.forbidden()

    def issue(self,session,stored,*,review=None,known_instance=None,dependency=None):
        draft=stored.draft;self._scope(session,draft)
        if (review is None)==(dependency is None):raise AnnualAccountsError.invalid_input()
        if review is not None:
            review.record.assert_draft(draft);stage=review.record.stage
            role=Port.PERSON if stage is Stage.SIGN else Port.SYSTEM_USER
            key=(draft.filing_id,role,stage)
            if not stored.recorded_at.value<=review.recorded_at.value<=self.now().value:raise AnnualAccountsError.unavailable()
        else:
            dependency.record.binding.assert_draft(draft);stage=None;role=Port.KNOWN_READ
            key=(draft.filing_id,role,dependency.record.sha256)
        with self._lock:
            if key in self._ports:return self._ports[key]
            filings={item[0] for item in self._ports}
            if (draft.filing_id not in filings and len(filings)>=self._maximum_filings
                    or not self.now().value<self._expires.value):raise AnnualAccountsError.unavailable()
            issued=self.now();expiry=Timestamp(min(issued.value+timedelta(seconds=300),self._expires.value))
            credential=self._credentials[(role,stage)]
            grant=Admission(Binding(draft.filing_id,draft.source.company_id,draft.source.income_year,draft.prepared_by,draft.sha256),
                role,self._run,self._organization,self._origin,self._database,hashlib.sha256(credential.encode()).hexdigest(),
                issued,expiry,64 if stage is Stage.PREPARE else 16,review.record.sha256 if review else None,
                known_instance,stage,dependency.record.sha256 if dependency else None)
            runtime=AccountsRehearsalRuntime(AccountsRehearsalCredential(grant,credential),now=self._now)
            port=self._builders[(role,stage)](runtime);self._ports[key]=port
            return port

    def retained(self,session,admission):
        with self._lock:
            matches=[port for port in self._ports.values() if port.runtime.admission==admission]
        if len(matches)!=1:raise AnnualAccountsError.unavailable()
        matches[0].runtime.assert_session(session);return matches[0]
