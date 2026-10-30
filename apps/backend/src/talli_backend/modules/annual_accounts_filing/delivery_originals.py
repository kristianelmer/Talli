"""Exact RR0002 read originals and a strict, locally supported metadata subset."""
from dataclasses import dataclass
from enum import StrEnum
import base64
import hashlib
import json
import re
from uuid import UUID

from talli_backend.shared.kernel import Timestamp
from .delivery import _canonical

APP_ID='brg/aarsregnskap-vanlig-202406'


def _uuid(value):
    if type(value) is not str or str(UUID(value))!=value:raise ValueError('Accounts data identity is invalid.')
    return value


def _instance(value):
    if type(value) is not str or re.fullmatch(r'[1-9][0-9]{0,18}/[0-9a-f-]{36}',value) is None:
        raise ValueError('Accounts instance identity is invalid.')
    party,identity=value.split('/');_uuid(identity)
    return party,identity


def _bytes(value):
    if type(value) is not str or len(value)>24*1024*1024:raise ValueError('Accounts original exceeds its bound.')
    raw=base64.b64decode(value,validate=True)
    if len(raw)>16*1024*1024 or base64.b64encode(raw).decode('ascii')!=value:raise ValueError('Accounts original encoding is invalid.')
    return raw


def _http_result(status,media,body,failure):
    if failure not in (None,'timeout','connection_lost','response_too_large','response_invalid','cancelled'):
        raise ValueError('Accounts HTTP failure code is unsupported.')
    if status is None:
        if failure is None or media is not None or body is not None:raise ValueError('Accounts uncertainty has no invented HTTP response.')
        return None
    if (type(status) is not int or not 100<=status<=599
            or media is not None and (type(media) is not str or len(media)>8192)):raise ValueError()
    return _bytes(body)


def _json_original(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate Accounts original key.')
            result[key]=value
        return result
    def constant(_):raise ValueError('Nonfinite Accounts original.')
    try:
        value=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=pairs,parse_constant=constant)
        pending=[(value,1)];count=0
        while pending:
            item,depth=pending.pop();count+=1
            if count>100000 or depth>64:raise ValueError('Accounts original structure exceeds its bound.')
            if isinstance(item,dict):pending.extend((child,depth+1) for child in item.values())
            elif isinstance(item,list):pending.extend((child,depth+1) for child in item)
        return value
    except (UnicodeError,RecursionError,OverflowError):raise ValueError('Accounts JSON original is unsupported.') from None


class AnnualAccountsReadPurpose(StrEnum):
    INSTANCE='instance'
    MAIN_FORM='main_form'
    COMPANY_ACCOUNTS='company_accounts'
    VALIDATION='validation'
    PDF='pdf'
    SIGNATURE='signature'


@dataclass(frozen=True,slots=True)
class AnnualAccountsDeliveryOriginal:
    purpose: AnnualAccountsReadPurpose
    instance_id: str
    data_id: str | None
    content_type: str | None
    body_base64: str | None
    observed_at: Timestamp
    http_status: int | None = 200
    failure_code: str | None = None
    requested_at: Timestamp | None = None

    def __post_init__(self):
        _instance(self.instance_id)
        if type(self.purpose) is not AnnualAccountsReadPurpose or type(self.observed_at) is not Timestamp:raise ValueError('Accounts read original is invalid.')
        if self.requested_at is None:object.__setattr__(self,'requested_at',self.observed_at)
        if type(self.requested_at) is not Timestamp or self.requested_at.value>self.observed_at.value:raise ValueError('Accounts read interval is invalid.')
        file=self.purpose not in (AnnualAccountsReadPurpose.INSTANCE,AnnualAccountsReadPurpose.VALIDATION)
        if file:_uuid(self.data_id)
        elif self.data_id is not None:raise ValueError('Accounts metadata read has no data identity.')
        _http_result(self.http_status,self.content_type,self.body_base64,self.failure_code)

    @property
    def raw_bytes(self):return _bytes(self.body_base64)

    @property
    def media_type(self):return self.content_type.split(';',1)[0].strip().lower() if self.content_type else None

    @property
    def sha256(self):return hashlib.sha256(self.raw_bytes).hexdigest() if self.body_base64 is not None else None

    @property
    def canonical_json(self):return _canonical({'version':'annual-accounts-read-original-v1','original':self})

    @property
    def evidence_sha256(self):return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()


@dataclass(frozen=True,slots=True)
class AnnualAccountsDataElement:
    data_id: str
    data_type: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True,slots=True)
class AnnualAccountsInstanceInspection:
    instance_id: str
    organization_number: str
    task: str | None
    ended_at: Timestamp | None
    archived: bool
    archived_at: Timestamp | None
    data: tuple[AnnualAccountsDataElement,...]
    original_sha256: str


def _time(value):
    from datetime import datetime
    if type(value) is not str:raise ValueError('Accounts process time is invalid.')
    return Timestamp(datetime.fromisoformat(value))


def inspect_annual_accounts_instance(original,*,organization_number):
    if (type(original) is not AnnualAccountsDeliveryOriginal or original.purpose is not AnnualAccountsReadPurpose.INSTANCE
            or original.http_status!=200 or original.failure_code is not None or original.media_type!='application/json'):raise ValueError()
    return _inspect_instance_bytes(original.raw_bytes,original.instance_id,organization_number,original.observed_at)


def _inspect_instance_bytes(raw,instance_id,organization_number,observed_at):
    if type(organization_number) is not str or re.fullmatch('[0-9]{9}',organization_number) is None:raise ValueError()
    value=_json_original(raw)
    if (type(value) is not dict or value.get('id')!=instance_id or value.get('appId')!=APP_ID
            or type(value.get('instanceOwner')) is not dict):raise ValueError('Accounts instance scope is unavailable.')
    owner=value['instanceOwner'];party,_=_instance(instance_id)
    if (owner.get('organisationNumber')!=organization_number or type(owner.get('partyId')) not in (int,str)
            or str(owner['partyId'])!=party):raise ValueError('Accounts instance owner differs.')
    process=value.get('process');status=value.get('status')
    if type(process) is not dict or type(status) is not dict or type(status.get('isArchived')) is not bool:
        raise ValueError('Accounts process metadata is incomplete.')
    current=process.get('currentTask');ended=None;task=None
    if current is None:
        ended=_time(process.get('ended'))
    else:
        if (type(current) is not dict or current.get('elementId') not in ('Utfylling','Signering')
                or current.get('altinnTaskType')!={'Utfylling':'data','Signering':'signing'}[current['elementId']]
                or process.get('ended') is not None):raise ValueError('Accounts process task is unsupported.')
        task=current['elementId']
    archived=status['isArchived'];archived_at=_time(status.get('archived')) if archived else None
    if not archived and status.get('archived') is not None:raise ValueError('Accounts archive flags contradict its timestamp.')
    if archived and ended is None:raise ValueError('Accounts archived metadata contradicts its active task.')
    if archived_at is not None and archived_at.value<ended.value:raise ValueError('Accounts archive predates process completion.')
    if (type(observed_at) is not Timestamp or any(value is not None and value.value>observed_at.value for value in (ended,archived_at))):
        raise ValueError('Accounts process completion is after its observation.')
    rows=value.get('data')
    if type(rows) is not list or not 2<=len(rows)<=8:raise ValueError('Accounts data enumeration is incomplete.')
    media={'Hovedskjema':'application/xml','Underskjema':'application/xml','ref-data-as-pdf':'application/pdf','signature':'application/json'}
    identities=set();data=[]
    for row in rows:
        if (type(row) is not dict or row.get('dataType') not in media or row.get('contentType')!=media[row['dataType']]
                or type(row.get('size')) is not int or not 0<=row['size']<=16*1024*1024
                or row.get('fileScanResult') not in (None,'Clean','NotApplicable')):
            raise ValueError('Accounts data profile or scan status is unsupported.')
        identity=_uuid(row.get('id'))
        if identity in identities:raise ValueError('Accounts data identities are ambiguous.')
        identities.add(identity);data.append(AnnualAccountsDataElement(identity,row['dataType'],row['contentType'],row['size']))
    if any(sum(item.data_type==kind for item in data)!=1 for kind in ('Hovedskjema','Underskjema')):
        raise ValueError('Accounts structured data extent differs from its standalone profile.')
    if sum(item.data_type=='signature' for item in data)>1 or sum(item.data_type=='ref-data-as-pdf' for item in data)>4:
        raise ValueError('Accounts generated original extent is unsupported.')
    return AnnualAccountsInstanceInspection(instance_id,organization_number,task,ended,archived,archived_at,tuple(data),hashlib.sha256(raw).hexdigest())


def inspect_annual_accounts_validation(original):
    """A recognized validation response; the exact raw response stays retained."""
    if (type(original) is not AnnualAccountsDeliveryOriginal or original.purpose is not AnnualAccountsReadPurpose.VALIDATION
            or original.http_status!=200 or original.failure_code is not None or original.media_type!='application/json'):raise ValueError()
    value=_json_original(original.raw_bytes)
    if type(value) is dict:
        if set(value)!={'validationIssues'}:raise ValueError('Accounts validation response has unknown controlling fields.')
        value=value['validationIssues']
    if type(value) is not list or len(value)>10000:raise ValueError('Accounts validation extent is unsupported.')
    severities={1:'error',2:'warning',3:'informational',4:'fixed',5:'success'};issues=[]
    for issue in value:
        if type(issue) is not dict:raise ValueError('Accounts validation issue is malformed.')
        severity=issue.get('severity')
        if type(severity) is int:severity=severities.get(severity)
        elif type(severity) is str:severity=severity.lower()
        else:raise ValueError('Accounts validation severity is malformed.')
        if severity not in severities.values():raise ValueError('Accounts validation severity is unsupported.')
        from .public import _freeze
        issues.append(_freeze(issue|{'severity':severity}))
    return tuple(issues)
