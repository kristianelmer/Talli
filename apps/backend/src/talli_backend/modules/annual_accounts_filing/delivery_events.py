"""Exact review, finite role admission and submit-once Accounts operation records."""
from dataclasses import dataclass,fields
from datetime import datetime
from enum import StrEnum
import base64
import hashlib
import json
import re
from urllib.parse import urlsplit

from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,IdempotencyKey,IncomeYear,Timestamp,UserId
from .delivery import _canonical
from .delivery_originals import APP_ID,_uuid,_instance,_http_result,AnnualAccountsDeliveryOriginal,AnnualAccountsReadPurpose


def _sha(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}',value) is None:raise ValueError('Accounts evidence hash is invalid.')
    return value


class AnnualAccountsDeliveryStage(StrEnum):
    PREPARE='prepare'
    CONFIRM='confirm'
    SIGN='sign'


class AnnualAccountsAuthorityPort(StrEnum):
    SYSTEM_USER='system_user'
    PERSON='person'
    KNOWN_READ='known_read'


class AnnualAccountsDeliveryAction(StrEnum):
    CREATE_INSTANCE='create_instance'
    UPLOAD_MAIN_FORM='upload_main_form'
    UPLOAD_COMPANY_ACCOUNTS='upload_company_accounts'
    CONFIRM='confirm'
    SIGN='sign'


@dataclass(frozen=True,slots=True)
class AnnualAccountsDeliveryBinding:
    filing_id: str
    company_id: CompanyId
    income_year: IncomeYear
    actor_id: ActorId
    draft_sha256: str

    def __post_init__(self):
        _uuid(self.filing_id);_sha(self.draft_sha256)
        if (type(self.company_id) is not CompanyId or type(self.income_year) is not IncomeYear
                or type(self.income_year.value) is not int or int(self.income_year)!=2025
                or type(self.actor_id) is not ActorId or self.actor_id.kind is not ActorKind.USER
                or type(self.actor_id.subject) is not UserId):raise ValueError('Accounts operation scope is invalid.')

    def assert_draft(self,draft):
        if (self.filing_id!=draft.filing_id or self.company_id!=draft.source.company_id
                or self.income_year!=draft.source.income_year or self.actor_id!=draft.prepared_by
                or self.draft_sha256!=draft.sha256):raise ValueError('Accounts operation differs from its retained draft.')


class _Record:
    __slots__=()
    @property
    def canonical_json(self):return _canonical({'version':self.codec_version,'record':self})
    @property
    def sha256(self):return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()


@dataclass(frozen=True,slots=True)
class AnnualAccountsDeliveryReview(_Record):
    binding: AnnualAccountsDeliveryBinding
    stage: AnnualAccountsDeliveryStage
    source_sha256: str
    reviewed_evidence_sha256: str
    documents_checked: bool
    action_confirmed: bool
    command_key: IdempotencyKey
    reviewed_at: Timestamp
    codec_version='annual-accounts-delivery-review-v1'

    def __post_init__(self):
        if (type(self.binding) is not AnnualAccountsDeliveryBinding or type(self.stage) is not AnnualAccountsDeliveryStage
                or self.documents_checked is not True or self.action_confirmed is not True
                or type(self.command_key) is not IdempotencyKey or type(self.reviewed_at) is not Timestamp):
            raise ValueError('Accounts review requires two explicit owner choices.')
        _sha(self.source_sha256);_sha(self.reviewed_evidence_sha256)

    @property
    def slot(self):return 'review:'+self.stage.value

    def assert_draft(self,draft):
        self.binding.assert_draft(draft)
        if self.source_sha256!=draft.source.sha256:raise ValueError('Accounts reviewed source differs from the draft.')


@dataclass(frozen=True,slots=True)
class AnnualAccountsFiniteAdmission(_Record):
    binding: AnnualAccountsDeliveryBinding
    port: AnnualAccountsAuthorityPort
    run_id: str
    organization_number: str
    origin: str
    database_scope_sha256: str
    credential_sha256: str
    issued_at: Timestamp
    expires_at: Timestamp
    maximum_requests: int
    review_sha256: str | None = None
    known_instance: str | None = None
    stage: AnnualAccountsDeliveryStage | None = None
    dependency_intent_sha256: str | None = None
    codec_version='annual-accounts-finite-admission-v1'

    def __post_init__(self):
        if (type(self.binding) is not AnnualAccountsDeliveryBinding or type(self.port) is not AnnualAccountsAuthorityPort
                or type(self.issued_at) is not Timestamp or type(self.expires_at) is not Timestamp
                or type(self.organization_number) is not str or re.fullmatch('[0-9]{9}',self.organization_number) is None
                or type(self.maximum_requests) is not int or not 1<=self.maximum_requests<=64
                or not 0<(self.expires_at.value-self.issued_at.value).total_seconds()<=300):
            raise ValueError('Accounts admission is not finite.')
        _uuid(self.run_id);_sha(self.database_scope_sha256);_sha(self.credential_sha256)
        if type(self.origin) is not str:raise ValueError()
        origin=urlsplit(self.origin)
        if (origin.scheme!='http' or origin.hostname!='127.0.0.1' or origin.port is None
                or not 1024<=origin.port<=65535 or self.origin!='http://127.0.0.1:'+str(origin.port)):
            raise ValueError('Accounts admission requires the exact finite loopback origin.')
        if self.port is AnnualAccountsAuthorityPort.KNOWN_READ:
            _instance(self.known_instance)
            _sha(self.dependency_intent_sha256)
            if self.stage is not None or self.review_sha256 is not None or self.maximum_requests>16:
                raise ValueError('Known-read admission cannot carry mutation authority.')
        else:
            _sha(self.review_sha256)
            if type(self.stage) is not AnnualAccountsDeliveryStage or self.dependency_intent_sha256 is not None:raise ValueError()
            if self.port is AnnualAccountsAuthorityPort.SYSTEM_USER and self.stage is AnnualAccountsDeliveryStage.PREPARE:
                if self.known_instance is not None:raise ValueError('Preparation admission cannot infer a created instance.')
            else:
                _instance(self.known_instance)
                if self.maximum_requests>16:raise ValueError('Accounts confirmation/person budget exceeds its bound.')
                if ((self.port is AnnualAccountsAuthorityPort.SYSTEM_USER and self.stage is not AnnualAccountsDeliveryStage.CONFIRM)
                        or (self.port is AnnualAccountsAuthorityPort.PERSON and self.stage is not AnnualAccountsDeliveryStage.SIGN)):
                    raise ValueError('Accounts admission stage differs from its actor port.')

    @property
    def slot(self):return 'admission:'+self.port.value+':'+(self.stage.value if self.stage else self.dependency_intent_sha256)

    def assert_current(self,now):
        if type(now) is not Timestamp or not self.issued_at.value<=now.value<self.expires_at.value:
            raise ValueError('Accounts finite admission is outside its time window.')


@dataclass(frozen=True,slots=True)
class AnnualAccountsDeliveryIntent(_Record):
    binding: AnnualAccountsDeliveryBinding
    action: AnnualAccountsDeliveryAction
    review_sha256: str
    admission_sha256: str
    prerequisite_sha256: str
    target_instance: str | None
    target_data: str | None
    request_method: str
    request_path: str
    request_content_type: str
    request_body_base64: str
    codec_version='annual-accounts-delivery-intent-v1'

    def __post_init__(self):
        if type(self.binding) is not AnnualAccountsDeliveryBinding or type(self.action) is not AnnualAccountsDeliveryAction:raise ValueError()
        for value in (self.review_sha256,self.admission_sha256,self.prerequisite_sha256):_sha(value)
        if self.action is AnnualAccountsDeliveryAction.CREATE_INSTANCE:
            if self.target_instance is not None or self.target_data is not None:raise ValueError('Creation cannot infer an instance identity.')
            path='/'+APP_ID+'/instances/create';method='POST';media='application/json'
        else:
            _instance(self.target_instance);path='/'+APP_ID+'/instances/'+self.target_instance
            method='PUT'
            if self.action in (AnnualAccountsDeliveryAction.UPLOAD_MAIN_FORM,AnnualAccountsDeliveryAction.UPLOAD_COMPANY_ACCOUNTS):
                _uuid(self.target_data);path+='/data/'+self.target_data;media='application/xml'
            else:
                if self.target_data is not None:raise ValueError('Process action has no file target.')
                path+='/process/next';media='application/json'
        if (self.request_path!=path or self.request_method!=method or self.request_content_type!=media
                or type(self.request_body_base64) is not str or len(self.request_body_base64)>12*1024*1024):raise ValueError('Accounts operation request differs from its fixed path.')
        raw=base64.b64decode(self.request_body_base64,validate=True)
        if not raw or base64.b64encode(raw).decode('ascii')!=self.request_body_base64:raise ValueError('Accounts operation body is invalid.')

    @property
    def slot(self):return 'intent:'+self.action.value

    @property
    def request_bytes(self):return base64.b64decode(self.request_body_base64,validate=True)

    def assert_draft(self,draft,review,admission):
        self.binding.assert_draft(draft);review.assert_draft(draft)
        if (review.binding!=self.binding or admission.binding!=self.binding or review.sha256!=self.review_sha256
                or admission.sha256!=self.admission_sha256 or admission.organization_number!=draft.source.organization_number
                or admission.review_sha256!=review.sha256 or admission.stage is not review.stage):raise ValueError('Accounts operation scope differs from its review/admission.')
        if self.action is AnnualAccountsDeliveryAction.SIGN:
            if (review.stage is not AnnualAccountsDeliveryStage.SIGN or admission.port is not AnnualAccountsAuthorityPort.PERSON
                    or admission.review_sha256!=review.sha256 or admission.known_instance!=self.target_instance):
                raise ValueError('Only the separately reviewed person port may request signing.')
            raw=b'{"action":"sign"}'
        else:
            if admission.port is not AnnualAccountsAuthorityPort.SYSTEM_USER:raise ValueError('Only the system preparation port may prepare.')
            if self.action is AnnualAccountsDeliveryAction.CONFIRM:
                if review.stage is not AnnualAccountsDeliveryStage.CONFIRM or admission.known_instance!=self.target_instance:
                    raise ValueError('Accounts lock needs its validation review and known target.')
                raw=b'{"action":"confirm"}'
            else:
                if review.stage is not AnnualAccountsDeliveryStage.PREPARE:raise ValueError('Accounts preparation needs its draft review.')
                raw=(b'{"instanceOwner":{"organisationNumber":"'+draft.source.organization_number.encode()+b'"}}'
                    if self.action is AnnualAccountsDeliveryAction.CREATE_INSTANCE else
                    draft.main_form_xml.encode('utf-8') if self.action is AnnualAccountsDeliveryAction.UPLOAD_MAIN_FORM else draft.company_accounts_xml.encode('utf-8'))
        if self.request_bytes!=raw:raise ValueError('Accounts operation body differs from the exact reviewed documents/action.')


@dataclass(frozen=True,slots=True)
class AnnualAccountsDeliveryCompletion(_Record):
    binding: AnnualAccountsDeliveryBinding
    action: AnnualAccountsDeliveryAction
    intent_sha256: str
    http_status: int | None
    response_content_type: str | None
    response_body_base64: str | None
    failure_code: str | None
    codec_version='annual-accounts-delivery-completion-v1'

    def __post_init__(self):
        if type(self.binding) is not AnnualAccountsDeliveryBinding or type(self.action) is not AnnualAccountsDeliveryAction:raise ValueError()
        _sha(self.intent_sha256)
        _http_result(self.http_status,self.response_content_type,self.response_body_base64,self.failure_code)

    @property
    def slot(self):return 'completion:'+self.action.value


@dataclass(frozen=True,slots=True)
class AnnualAccountsDeliveryObservation(_Record):
    binding: AnnualAccountsDeliveryBinding
    observation_id: str
    admission_sha256: str
    intent_sha256: str
    original: AnnualAccountsDeliveryOriginal
    codec_version='annual-accounts-delivery-observation-v1'

    def __post_init__(self):
        _uuid(self.observation_id);_sha(self.admission_sha256);_sha(self.intent_sha256)
        if type(self.binding) is not AnnualAccountsDeliveryBinding or type(self.original) is not AnnualAccountsDeliveryOriginal:raise ValueError()

    @property
    def slot(self):return 'observation:'+self.observation_id


class AnnualAccountsFrameKind(StrEnum):
    CREATE_TARGET='create_target'
    MAIN_UPLOADED='main_uploaded'
    UPLOAD_REVIEW='upload_review'
    SIGN_REVIEW='sign_review'
    ARCHIVE='archive'


@dataclass(frozen=True,slots=True)
class AnnualAccountsDeliveryFrameRecord(_Record):
    binding: AnnualAccountsDeliveryBinding
    frame_id: str
    kind: AnnualAccountsFrameKind
    observation_sha256: tuple[str,...]
    codec_version='annual-accounts-delivery-frame-v1'

    def __post_init__(self):
        _uuid(self.frame_id)
        if (type(self.binding) is not AnnualAccountsDeliveryBinding or type(self.kind) is not AnnualAccountsFrameKind
                or not isinstance(self.observation_sha256,(tuple,list)) or not 1<=len(self.observation_sha256)<=12):raise ValueError()
        object.__setattr__(self,'observation_sha256',tuple(self.observation_sha256))
        if len(set(self.observation_sha256))!=len(self.observation_sha256):raise ValueError('Accounts frame references are ambiguous.')
        for value in self.observation_sha256:_sha(value)

    @property
    def slot(self):return 'frame:'+self.frame_id


def decode_annual_accounts_delivery_record(raw,expected_sha256):
    """Known exact record generations only; a digest never excuses lossy decoding."""
    def obj(value,keys):
        if type(value) is not dict or set(value)!=set(keys):raise ValueError()
        return value
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError()
            result[key]=value
        return result
    def constant(_):raise ValueError()
    def scalar(value):return obj(value,('value',))['value']
    def timestamp(value):return Timestamp(datetime.fromisoformat(scalar(value)))
    def binding(value):
        value=obj(value,('filing_id','company_id','income_year','actor_id','draft_sha256'))
        year=scalar(value['income_year']);actor=obj(value['actor_id'],('kind','subject'))
        if type(year) is not int:raise ValueError()
        return AnnualAccountsDeliveryBinding(value['filing_id'],CompanyId(scalar(value['company_id'])),IncomeYear(year),
            ActorId(ActorKind(actor['kind']),UserId(scalar(actor['subject']))),value['draft_sha256'])
    try:
        if (type(raw) is not str or len(raw.encode('utf-8'))>32*1024*1024
                or hashlib.sha256(raw.encode('utf-8')).hexdigest()!=expected_sha256):raise ValueError()
        root=obj(json.loads(raw,object_pairs_hook=pairs,parse_constant=constant),('version','record'))
        classes={kind.codec_version:kind for kind in (AnnualAccountsDeliveryReview,AnnualAccountsFiniteAdmission,
            AnnualAccountsDeliveryIntent,AnnualAccountsDeliveryCompletion,AnnualAccountsDeliveryObservation,AnnualAccountsDeliveryFrameRecord)}
        cls=classes[root['version']];value=obj(root['record'],(field.name for field in fields(cls)))
        value=value|{'binding':binding(value['binding'])}
        if cls is AnnualAccountsDeliveryReview:
            value.update(stage=AnnualAccountsDeliveryStage(value['stage']),command_key=IdempotencyKey(scalar(value['command_key'])),
                reviewed_at=timestamp(value['reviewed_at']))
        elif cls is AnnualAccountsFiniteAdmission:
            value.update(port=AnnualAccountsAuthorityPort(value['port']),issued_at=timestamp(value['issued_at']),expires_at=timestamp(value['expires_at']),
                stage=AnnualAccountsDeliveryStage(value['stage']) if value['stage'] is not None else None)
        elif cls in (AnnualAccountsDeliveryIntent,AnnualAccountsDeliveryCompletion):value['action']=AnnualAccountsDeliveryAction(value['action'])
        elif cls is AnnualAccountsDeliveryFrameRecord:value['kind']=AnnualAccountsFrameKind(value['kind'])
        else:
            original=obj(value['original'],(field.name for field in fields(AnnualAccountsDeliveryOriginal)))
            value['original']=AnnualAccountsDeliveryOriginal(**(original|{'purpose':AnnualAccountsReadPurpose(original['purpose']),
                'observed_at':timestamp(original['observed_at']),'requested_at':timestamp(original['requested_at'])}))
        record=cls(**value)
        if record.canonical_json!=raw:raise ValueError()
        return record
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        raise ValueError('Retained Accounts operation record is invalid or its exact bytes changed.') from None
