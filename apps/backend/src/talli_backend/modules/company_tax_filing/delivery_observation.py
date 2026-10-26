"""Exact finite-admission and instance-read originals for subsequent Tax stages.

Unknown response structure is retained as unknown, never as an empty instance.
Explicitly foreign scope is rejected. This file does not authorize a mutation.
"""
from __future__ import annotations

from dataclasses import dataclass,field
from datetime import datetime
from enum import StrEnum
import hashlib
import re
from urllib.parse import urlsplit

from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,IncomeYear,Timestamp,UserId
from .delivery import _digest,_json,tax_delivery_digest
from .delivery_approval import TaxDeliveryReviewApproval
from .delivery_draft import TaxDeliveryDraft,_canonical,_object
from .delivery_journal import _bytes,_instance,_response_object,_uuid

_APP_ID='skd/formueinntekt-skattemelding-v2'


class TaxDeliveryOriginalPurpose(StrEnum):
    ADMISSION='finite_admission'
    INSTANCE='instance'
    ENVELOPE='envelope'


@dataclass(frozen=True,slots=True)
class TaxDeliveryReadOriginal:
    purpose: TaxDeliveryOriginalPurpose
    body_base64: str
    content_type: str
    http_status: int | None

    def __post_init__(self):
        if type(self.purpose) is not TaxDeliveryOriginalPurpose:raise ValueError('Tax original purpose is invalid.')
        expected={'application/json'} if self.purpose in (TaxDeliveryOriginalPurpose.ADMISSION,TaxDeliveryOriginalPurpose.INSTANCE) else {'application/xml','text/xml'}
        if type(self.content_type) is not str or self.content_type not in expected:raise ValueError('Tax original content type is invalid.')
        if self.purpose is TaxDeliveryOriginalPurpose.ADMISSION:
            if self.http_status is not None:raise ValueError('A local admission is not an HTTP response.')
        elif type(self.http_status) is not int or self.http_status!=200:
            raise ValueError('Tax read original HTTP status is invalid.')
        _bytes(self.body_base64)

    @property
    def raw_bytes(self) -> bytes:return _bytes(self.body_base64)

    @property
    def sha256(self) -> str:return hashlib.sha256(self.raw_bytes).hexdigest()


def _scope(value):
    _uuid(value.filing_id);_digest(value.approval_sha256)
    if (type(value.company_id) is not CompanyId or type(value.income_year) is not IncomeYear
            or type(value.income_year.value) is not int or int(value.income_year)!=2025
            or type(value.approved_by) is not ActorId or value.approved_by.kind is not ActorKind.USER
            or type(value.approved_by.subject) is not UserId):
        raise ValueError('Tax observation scope is invalid.')


@dataclass(frozen=True,slots=True)
class TaxDeliveryAdmissionEvidence:
    filing_id: str
    company_id: CompanyId
    income_year: IncomeYear
    approved_by: ActorId
    approval_sha256: str
    original: TaxDeliveryReadOriginal

    def __post_init__(self):
        _scope(self)
        if type(self.original) is not TaxDeliveryReadOriginal or self.original.purpose is not TaxDeliveryOriginalPurpose.ADMISSION:
            raise ValueError('Tax admission original is invalid.')
        value=_object(_response_object(self.original.raw_bytes),('version','runId','companyId','incomeYear','actorId',
            'filingId','draftSha256','organizationNumber','issuedAt','expiresAt','origin','credentialSha256',
            'databaseScopeSha256','maximumRequests'))
        if (value['version']!='tax-loopback-admission-v1' or value['companyId']!=str(self.company_id)
                or type(value['incomeYear']) is not int or value['incomeYear']!=int(self.income_year)
                or value['actorId']!=str(self.approved_by.subject) or value['filingId']!=self.filing_id
                or self.original.raw_bytes.decode('utf-8')!=_canonical(value)):
            raise ValueError('Tax admission context scope is invalid.')
        _uuid(value['runId'])
        for name in ('draftSha256','credentialSha256','databaseScopeSha256'):_digest(value[name])
        if any(type(value[name]) is not str for name in ('issuedAt','expiresAt','origin')):
            raise ValueError('Tax admission times and origin must be text.')
        issued=Timestamp(datetime.fromisoformat(value['issuedAt']));expires=Timestamp(datetime.fromisoformat(value['expiresAt']))
        origin=urlsplit(value['origin'])
        if (type(value['maximumRequests']) is not int or not 1<=value['maximumRequests']<=1000
                or not 0<(expires.value-issued.value).total_seconds()<=3600
                or type(value['organizationNumber']) is not str or re.fullmatch('[0-9]{9}',value['organizationNumber']) is None
                or origin.scheme!='http' or origin.hostname!='127.0.0.1' or origin.port is None
                or not 1024<=origin.port<=65535 or value['origin']!='http://127.0.0.1:'+str(origin.port)):
            raise ValueError('Tax admission context is not finite.')

    @property
    def canonical_json(self) -> str:
        return _canonical({'version':'company-tax-delivery-admission-v1','admission':_json(self)})

    @property
    def sha256(self) -> str:return hashlib.sha256(self.canonical_json.encode()).hexdigest()

    def assert_approval(self,approval: TaxDeliveryReviewApproval,draft: TaxDeliveryDraft) -> None:
        approval.assert_draft(draft)
        value=_response_object(self.original.raw_bytes)
        if (self.filing_id!=approval.filing_id or self.company_id!=approval.company_id
                or self.income_year!=approval.income_year or self.approved_by!=approval.approved_by
                or self.approval_sha256!=approval.sha256 or self.original.sha256!=approval.authority_context_sha256
                or value['draftSha256']!=draft.sha256 or value['organizationNumber']!=draft.envelope.source.organization_number):
            raise ValueError('Tax admission evidence differs from the retained approval.')


@dataclass(frozen=True,slots=True)
class TaxDeliveryDataElement:
    data_id: str
    data_type: str
    content_type: str
    size_bytes: int
    scan_result: str


@dataclass(frozen=True,slots=True)
class TaxDeliveryInstanceInspection:
    instance_id: str
    process_task: str | None
    process_ended_at: Timestamp | None
    archived: bool | None
    archived_at: Timestamp | None
    data: tuple[TaxDeliveryDataElement,...]
    error_code: str | None=None

    @property
    def known(self):return self.error_code is None

    @property
    def empty_data(self):return self.known and not self.data

    @property
    def envelope(self):return next((row for row in self.data if row.data_type=='skattemeldingOgNaeringsspesifikasjon'),None)

    @property
    def feedback(self):return next((row for row in self.data if row.data_type=='tilbakemelding'),None)


class _ForeignInstance(ValueError):pass


def _time(value):
    if value is None:return None
    if type(value) is not str:raise ValueError()
    return Timestamp(datetime.fromisoformat(value))


def _inspect_instance(raw,instance_id,organization_number,income_year):
    try:
        value=_response_object(raw)
        # Recognizable foreign identity is never archived under another scope.
        identity=value.get('id')
        try:recognized_instance=_instance(identity)
        except (ValueError,TypeError,AttributeError):recognized_instance=None
        if recognized_instance is not None and recognized_instance!=instance_id:raise _ForeignInstance()
        app=value.get('appId')
        recognized_app=type(app) is str and re.fullmatch('[a-z0-9][a-z0-9-]{0,99}/[a-z0-9][a-z0-9-]{0,99}',app) is not None
        if recognized_app and app!=_APP_ID:raise _ForeignInstance()
        owner=value.get('instanceOwner');data_values=value.get('dataValues')
        organization=owner.get('organisationNumber') if type(owner) is dict else None
        recognized_organization=type(organization) is str and re.fullmatch('[0-9]{9}',organization) is not None
        if recognized_organization and organization!=organization_number:
            raise _ForeignInstance()
        if type(data_values) is dict and 'inntektsaar' in data_values:
            year=data_values['inntektsaar']
            recognized_year=(type(year) is int and 2000<=year<=2100) or (type(year) is str and re.fullmatch('[0-9]{4}',year) is not None and 2000<=int(year)<=2100)
            if recognized_year and str(year)!=str(int(income_year)):
                raise _ForeignInstance()
            if not recognized_year:raise ValueError()
        if (value.get('id')!=instance_id or value.get('appId')!=_APP_ID or type(owner) is not dict
                or owner.get('organisationNumber')!=organization_number or type(data_values) is not dict
                or 'inntektsaar' not in data_values):raise ValueError()
        process=value['process'];status=value['status'];elements=value['data']
        if type(process) is not dict or type(status) is not dict or type(elements) is not list or len(elements)>1000:
            raise ValueError()
        ended=_time(process.get('ended'));task=process.get('currentTask')
        if task is None:
            if ended is None:raise ValueError()
            task_type=None
        else:
            if type(task) is not dict or task.get('altinnTaskType') not in ('data','confirmation','feedback') or ended is not None:
                raise ValueError()
            task_type=task['altinnTaskType']
        archived=status['isArchived'];archived_at=_time(status.get('archived'))
        if type(archived) is not bool or (archived and (archived_at is None or ended is None)):
            raise ValueError()
        rows=[];ids=set();types=[]
        for element in elements:
            if type(element) is not dict:raise ValueError()
            identity=_uuid(element['id']);kind=element['dataType'];content=element['contentType'];size=element['size'];scan=element['fileScanResult']
            if (identity in ids or type(kind) is not str or not 0<len(kind)<=255
                    or type(content) is not str or not 0<len(content)<=255 or type(size) is not int or not 0<=size<=8*1024*1024
                    or type(scan) is not str or not 0<len(scan)<=80):raise ValueError()
            ids.add(identity);types.append(kind)
            rows.append(TaxDeliveryDataElement(identity,kind,content,size,scan))
        if any(types.count(kind)>1 for kind in ('skattemeldingOgNaeringsspesifikasjon','tilbakemelding')):raise ValueError()
        return TaxDeliveryInstanceInspection(instance_id,task_type,ended,archived,archived_at,tuple(rows))
    except _ForeignInstance:
        raise ValueError('Authority returned a different Tax instance scope.') from None
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        return TaxDeliveryInstanceInspection(instance_id,None,None,None,None,(),'instance_response_unavailable')


@dataclass(frozen=True,slots=True)
class TaxDeliveryInstanceObservation:
    filing_id: str
    company_id: CompanyId
    income_year: IncomeYear
    approved_by: ActorId
    approval_sha256: str
    organization_number: str
    instance_id: str
    original: TaxDeliveryReadOriginal
    observed_at: Timestamp
    _inspection: TaxDeliveryInstanceInspection=field(init=False,repr=False,compare=False)

    def __post_init__(self):
        _scope(self);_instance(self.instance_id)
        if (type(self.organization_number) is not str or re.fullmatch('[0-9]{9}',self.organization_number) is None
                or type(self.original) is not TaxDeliveryReadOriginal or self.original.purpose is not TaxDeliveryOriginalPurpose.INSTANCE
                or type(self.observed_at) is not Timestamp):
            raise ValueError('Tax instance observation is invalid.')
        object.__setattr__(self,'_inspection',_inspect_instance(self.original.raw_bytes,self.instance_id,self.organization_number,self.income_year))

    @property
    def inspection(self):return self._inspection

    @property
    def evidence_sha256(self):
        # Repeated unchanged polls can reuse the first original without changing
        # export generations. A later consequential intent retains fresh timing.
        return tax_delivery_digest(['tax-instance-read-identity-v1',self.filing_id,str(self.company_id),
            int(self.income_year),str(self.approved_by.subject),self.approval_sha256,
            self.organization_number,self.instance_id,self.original.sha256])

    @property
    def canonical_json(self):
        value=_json(self);value.pop('_inspection')
        return _canonical({'version':'company-tax-delivery-instance-observation-v1','observation':value})

    @property
    def sha256(self):return hashlib.sha256(self.canonical_json.encode()).hexdigest()

    def assert_approval(self,approval: TaxDeliveryReviewApproval,draft: TaxDeliveryDraft,instance_id: str):
        approval.assert_draft(draft)
        if (self.filing_id!=approval.filing_id or self.company_id!=approval.company_id or self.income_year!=approval.income_year
                or self.approved_by!=approval.approved_by or self.approval_sha256!=approval.sha256
                or self.organization_number!=draft.envelope.source.organization_number or self.instance_id!=instance_id):
            raise ValueError('Tax instance read does not bind the retained approval and instance.')


def _decode_original(value):
    value=_object(value,('purpose','body_base64','content_type','http_status'))
    return TaxDeliveryReadOriginal(**(value|{'purpose':TaxDeliveryOriginalPurpose(value['purpose'])}))


def decode_tax_delivery_observation(raw: str,expected_sha256: str):
    try:
        if (type(raw) is not str or len(raw.encode())>24*1024*1024
                or _digest(expected_sha256)!=hashlib.sha256(raw.encode()).hexdigest()):raise ValueError()
        value=_response_object(raw.encode())
        if value.get('version')=='company-tax-delivery-admission-v1':
            value=_object(value,('version','admission'));body=_object(value['admission'],
                ('filing_id','company_id','income_year','approved_by','approval_sha256','original'))
            kind=TaxDeliveryAdmissionEvidence
        elif value.get('version')=='company-tax-delivery-instance-observation-v1':
            value=_object(value,('version','observation'));body=_object(value['observation'],
                ('filing_id','company_id','income_year','approved_by','approval_sha256','organization_number','instance_id','original','observed_at'))
            observed=_object(body['observed_at'],('value',));body=body|{'observed_at':Timestamp(datetime.fromisoformat(observed['value']))}
            kind=TaxDeliveryInstanceObservation
        else:raise ValueError()
        company=_object(body['company_id'],('value',));year=_object(body['income_year'],('value',))
        actor=_object(body['approved_by'],('kind','subject'));subject=_object(actor['subject'],('value',))
        result=kind(**(body|{'company_id':CompanyId(company['value']),'income_year':IncomeYear(year['value']),
            'approved_by':ActorId(ActorKind(actor['kind']),UserId(subject['value'])),'original':_decode_original(body['original'])}))
        if result.canonical_json!=raw:raise ValueError()
        return result
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        raise ValueError('Retained Tax observation is invalid or its exact bytes changed.') from None
