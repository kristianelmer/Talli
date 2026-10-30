"""Accounts-owned exact preparation. This is neither common readiness nor authority."""
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import re
from uuid import UUID

from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IdempotencyKey, IncomeYear, Timestamp, UserId
from .delivery_documents import AnnualAccountsDocumentsInspection

SYNTHETIC_BOARD = 'annual_board_minutes'
SYNTHETIC_MEETING = 'annual_general_meeting_minutes'
SYNTHETIC_SIGNOFF_KIND = 'synthetic_accounts_signoff_v1'


def _json(value):
    if is_dataclass(value):return {field.name:_json(getattr(value,field.name)) for field in fields(value)}
    if isinstance(value,Mapping):
        if any(type(key) is not str for key in value):raise ValueError('Accounts evidence keys must be text.')
        return {key:_json(child) for key,child in value.items()}
    if isinstance(value,(list,tuple)):return [_json(child) for child in value]
    if isinstance(value,Decimal):
        if not value.is_finite():raise ValueError('Accounts amount must be finite.')
        return str(value)
    if isinstance(value,datetime):
        if value.utcoffset() is None:raise ValueError('Accounts evidence time needs a timezone.')
        return value.isoformat()
    if value is None or isinstance(value,(str,int,float,bool)):return value
    raise ValueError('Unsupported Accounts evidence value.')


def _canonical(value):return json.dumps(_json(value),sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def annual_accounts_delivery_digest(value):return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


@dataclass(frozen=True,slots=True)
class AnnualAccountsDeliverySource:
    """Complete owning reads from one verified repeatable SQL snapshot.

    The application supplies the Ledger-owned effective projection and complete
    retained snapshots. No caller readiness flag or mutable source object is kept.
    Every consequential operation must re-read this source under the company guard.
    """
    company_id: CompanyId
    income_year: IncomeYear
    organization_number: str
    legal_name: str
    annual_data: Mapping[str,object]
    ledger_entries: tuple[Mapping[str,object],...]
    owning_snapshots: Mapping[str,object]
    upstream_sha256: Mapping[str,str]

    def __post_init__(self):
        from .public import _freeze
        if (type(self.company_id) is not CompanyId or type(self.income_year) is not IncomeYear
                or type(self.income_year.value) is not int or int(self.income_year)!=2025
                or type(self.organization_number) is not str or re.fullmatch('[0-9]{9}',self.organization_number) is None
                or type(self.legal_name) is not str or not self.legal_name.strip()
                or not isinstance(self.annual_data,Mapping) or not isinstance(self.ledger_entries,(tuple,list))
                or not isinstance(self.owning_snapshots,Mapping) or set(self.owning_snapshots)!={'annual','ledger','corporate'}
                or not isinstance(self.upstream_sha256,Mapping) or set(self.upstream_sha256)!=set(self.owning_snapshots)):
            raise ValueError('Accounts owning source is incomplete or outside its supported scope.')
        for row in (self.annual_data,*self.ledger_entries):
            if (not isinstance(row,Mapping) or row.get('company_id')!=str(self.company_id)
                    or type(row.get('income_year')) is not int or row['income_year']!=int(self.income_year)):
                raise ValueError('Accounts owning row scope differs.')
        identities=[row.get('id') for row in self.ledger_entries]
        if any(type(value) is not str or not value for value in identities) or len(set(identities))!=len(identities):
            raise ValueError('Accounts effective ledger identities are ambiguous.')
        for name in ('annual_data','ledger_entries','owning_snapshots','upstream_sha256'):
            object.__setattr__(self,name,_freeze(_json(getattr(self,name))))
        if any(self.upstream_sha256[name]!=annual_accounts_delivery_digest(snapshot)
               for name,snapshot in self.owning_snapshots.items()):
            raise ValueError('Accounts retained owning snapshot differs from its read commitment.')
        history=self.owning_snapshots['annual']
        selected=[item for item in history if item['sourceId']==self.annual_data['id']]
        if len(selected)!=1:raise ValueError('Accounts retained Annual source is incomplete.')
        selected=selected[0]
        if (selected['companyId']!=str(self.company_id) or selected['incomeYear']!=int(self.income_year)
                or any(selected[original]!=self.annual_data[projected] for original,projected in (
                    ('answers','answers'),('confirmations','confirmations'),('noActivityConfirmed','no_activity_confirmed'),
                    ('annualFullTimeEquivalents','annual_full_time_equivalents'),('completedAt','completed_at'),('updatedAt','updated_at')))):
            raise ValueError('Accounts Annual projection differs from its retained original.')
        retained=self.owning_snapshots['ledger']
        if (retained['company_id']!={'value':str(self.company_id)}
                or retained['income_year']!={'value':int(self.income_year)}
                or [item['entry_id']['value'] for item in retained['effective_entries']]!=identities):
            raise ValueError('Accounts effective projection differs from its owning snapshot.')
        retained_ids=[item['entry_id']['value'] for item in retained['retained_entries']]
        if len(set(retained_ids))!=len(retained_ids) or not set(identities).issubset(retained_ids):
            raise ValueError('Accounts retained Ledger history is incomplete.')
        for original,projected in zip(retained['effective_entries'],self.ledger_entries,strict=True):
            if (original['company_id']!={'value':str(self.company_id)}
                    or original['income_year']!={'value':int(self.income_year)}
                    or original['entry_kind']!=projected['entry_type'] or original['memo']!=projected['memo']
                    or len(original['lines'])!=len(projected['lines'])
                    or tuple(flag['code'] for flag in original['risk_flags'])!=projected['risk_flags']
                    or (original['warning_accepted_at']['value'] if original['warning_accepted_at'] else None)!=projected['warning_accepted_at']):
                raise ValueError('Accounts effective entry differs from its owning snapshot.')
            for line,projection in zip(original['lines'],projected['lines'],strict=True):
                if (line['account']!=projection['account'] or line['description']!=projection['description']
                        or line['debit']['amount']!=projection['debit'] or line['credit']['amount']!=projection['credit']
                        or line['debit']['currency']!=projection['currency'] or line['credit']['currency']!=projection['currency']):
                    raise ValueError('Accounts effective line differs from its owning snapshot.')
        # Check JSON finiteness even before a draft is constructed.
        if len(_canonical(self).encode('utf-8'))>24*1024*1024:raise ValueError('Accounts source exceeds its retained bound.')

    @property
    def sha256(self):return annual_accounts_delivery_digest(self)


def _approval(source):
    def field(value,camel,snake):
        # Corporate's persisted public receipt uses camel case; its retained
        # predecessor uses snake case. Preserve both originals without mixing
        # or silently preferring contradictory representations.
        keys=[key for key in (camel,snake) if key in value]
        if len(keys)!=1:raise ValueError('Corporate canonical identity is missing or ambiguous.')
        return value[keys[0]]
    evidence=source.owning_snapshots['corporate'];ready=evidence['readiness']
    if (ready['company_id']!={'value':str(source.company_id)} or ready['income_year']!={'value':int(source.income_year)}
            or ready['decision_kind']!='annual_close' or ready['current_source_matches'] is not True):
        raise ValueError('Current Corporate annual-close evidence is required.')
    simulation=evidence.get('synthetic_signoff')
    if simulation is None:
        if (ready['finalized'] is not True or ready['annual_submission_ready'] is not True
                or ready['blockers'] or not ready['signed_artifact_hashes'] or ready['finalization_id'] is None):
            raise ValueError('Current finalized Corporate annual-close evidence is required.')
    else:
        if (set(evidence)!={'readiness','snapshot','synthetic_signoff'} or not isinstance(simulation,Mapping)
                or set(simulation)!={'kind','companyId','incomeYear','decisionId','decisionSha256','sourceSha256',
                    'unsignedDocumentSha256','expiresAt','statement'}
                or simulation['kind']!=SYNTHETIC_SIGNOFF_KIND or simulation['companyId']!=str(source.company_id)
                or type(simulation['incomeYear']) is not int or simulation['incomeYear']!=int(source.income_year)
                or simulation['decisionId']!=ready['decision_id']['value']
                or simulation['decisionSha256']!=ready['decision_hash']
                or simulation['sourceSha256']!=ready['source_hash']
                or simulation['unsignedDocumentSha256']!=ready['generated_artifact_hashes']
                or set(simulation['unsignedDocumentSha256'])!={SYNTHETIC_BOARD,SYNTHETIC_MEETING}
                or simulation['statement']!='Synthetic test sign-off only; originals are unsigned; no owner signed-copy attestation or finalization.'
                or type(simulation['expiresAt']) is not str
                or datetime.fromisoformat(simulation['expiresAt']).utcoffset() is None
                or ready['state']!='facts_approved' or ready['finalized'] is not False
                or ready['annual_submission_ready'] is not False or ready['finalization_id'] is not None
                or ready['signed_artifact_hashes'] or ready['source_hash']!=ready['current_source_hash']
                or {item['code'] for item in ready['blockers']}!={
                    'corporate_documents_missing_signed_artifacts','corporate_documents_finalization_required'}):
            raise ValueError('Synthetic Accounts sign-off evidence is invalid.')
    decisions=[item for item in evidence['snapshot']['decisions'] if item['decision_id']==ready['decision_id']]
    if len(decisions)!=1:raise ValueError('Corporate annual-close decision is ambiguous.')
    decision=decisions[0];value=decision['canonical_input']
    if (decision['company_id']!={'value':str(source.company_id)} or decision['income_year']!={'value':int(source.income_year)}
            or decision['decision_kind']!='annual_close' or decision['decision_hash']!=ready['decision_hash']
            or field(value,'companyId','company_id')!=str(source.company_id) or field(value,'incomeYear','income_year')!=int(source.income_year)
            or field(value,'organizationNumber','organization_number')!=source.organization_number or field(value,'legalName','legal_name')!=source.legal_name):
        raise ValueError('Corporate annual-close identity differs from current source.')
    if simulation is None:
        finals=[item for item in evidence['snapshot']['finalizations'] if item['finalization_id']==ready['finalization_id']]
        if (len(finals)!=1 or finals[0]['company_id']!=decision['company_id'] or finals[0]['income_year']!=decision['income_year']
                or finals[0]['decision_id']!=decision['decision_id'] or finals[0]['decision_hash']!=decision['decision_hash']
                or finals[0]['annual_close_source_id']!=decision['annual_close_source_id']
                or finals[0]['signed_artifact_hashes']!=ready['signed_artifact_hashes']):
            raise ValueError('Accounts retained Corporate finalization does not bind the signed decision.')
    else:
        if (decision['source_hash']!=simulation['sourceSha256']
                or any(item['decision_id']==decision['decision_id'] for item in evidence['snapshot']['finalizations'])
                or not any(item['decision_id']==decision['decision_id'] and item['event_kind']=='facts_approved'
                    and item['decision_hash']==decision['decision_hash'] for item in evidence['snapshot']['events'])):
            raise ValueError('Synthetic Accounts approval does not bind current facts.')
        artifacts=[item for item in evidence['snapshot']['artifacts']
            if item['document_set_id']==decision['document_set_id']]
        if (len(artifacts)!=2 or any(item['variant']!='unsigned' for item in artifacts)
                or {item['artifact_kind']:item['content_sha256'] for item in artifacts}!=simulation['unsignedDocumentSha256']):
            raise ValueError('Synthetic Accounts originals must remain unsigned.')
    approval=field(field(value,'generalMeeting','general_meeting'),'meetingDate','meeting_date')
    if type(approval) is not str or date.fromisoformat(approval).isoformat()!=approval:
        raise ValueError('Corporate approval date is invalid.')
    return approval


def annual_accounts_source_is_synthetic(source):
    return 'synthetic_signoff' in source.owning_snapshots['corporate']


_ACCOUNTS=frozenset(('1300','1310','1350','1800','1810','1815','1920','2000','2050','2255','2500',
    '7770','6700','6705','6420','7790','6720','7795','8070','8071','8074','8050','8090','8171','8174','8300'))
_EXPENSES=frozenset(('7770','6700','6705','6420','7790','6720','7795','8090','8171','8174'))


def _calculation_source(source):
    from .public import AnnualAccountsSource
    annual=source.annual_data
    if (not source.ledger_entries or type(annual.get('annual_full_time_equivalents')) not in (int,float)
            or annual['annual_full_time_equivalents']<0):raise ValueError('Accounts notes or ledger evidence is missing.')
    if any(str(flag).startswith('annual_accounts_') for flag in annual['confirmations']):
        raise ValueError('Accounts requires an unsupported regime or attachment.')
    balances={}
    for entry in source.ledger_entries:
        if entry['risk_flags'] and not entry['warning_accepted_at']:
            raise ValueError('Accounts ledger warnings need owner review.')
        for line in entry['lines']:
            account=line['account'];debit=Decimal(line['debit']);credit=Decimal(line['credit'])
            if (account not in _ACCOUNTS or line['currency']!='NOK' or not debit.is_finite() or not credit.is_finite()
                    or debit<0 or credit<0 or debit>0 and credit>0):
                raise ValueError('Accounts ledger profile cannot represent this line.')
            balances[account]=balances.get(account,Decimal(0))+debit-credit
    # This version has no rounding or extended-account policy. Reject rather
    # than lose cents, contra expenses, or precision in the frozen calculator.
    if any(value!=value.to_integral_value() or abs(value)>10**12 or account in _EXPENSES and value<0
            for account,value in balances.items()):raise ValueError('Accounts requires an unsupported amount projection.')
    projection={'company_id':str(source.company_id),'income_year':int(source.income_year),
        'lines':tuple({'account':account,'debit':str(max(value,Decimal(0))),
                      'credit':str(max(-value,Decimal(0)))} for account,value in sorted(balances.items()))}
    return AnnualAccountsSource(int(source.income_year),annual,(projection,))


@dataclass(frozen=True,slots=True)
class AnnualAccountsDeliveryDraft:
    filing_id: str
    command_key: IdempotencyKey
    prepared_by: ActorId
    source: AnnualAccountsDeliverySource
    contact_email: str
    confirming_representative: str
    main_form_xml: str
    company_accounts_xml: str
    inspection: AnnualAccountsDocumentsInspection

    def __post_init__(self):
        if (type(self.filing_id) is not str or str(UUID(self.filing_id))!=self.filing_id
                or type(self.command_key) is not IdempotencyKey or type(self.prepared_by) is not ActorId
                or self.prepared_by.kind is not ActorKind.USER or type(self.prepared_by.subject) is not UserId
                or type(self.source) is not AnnualAccountsDeliverySource or type(self.inspection) is not AnnualAccountsDocumentsInspection
                or any(type(value) is not str or not value or len(value.encode('utf-8'))>8*1024*1024
                       for value in (self.main_form_xml,self.company_accounts_xml))):raise ValueError('Accounts draft identity is invalid.')
        documents=_render(self.source,self.contact_email,self.confirming_representative)
        if (self.main_form_xml!=documents.main_form_xml or self.company_accounts_xml!=documents.company_accounts_xml
                or self.inspection.organization_number!=self.source.organization_number
                or self.inspection.income_year!=int(self.source.income_year)
                or self.inspection.main_form_sha256!=hashlib.sha256(self.main_form_xml.encode('utf-8')).hexdigest()
                or self.inspection.company_accounts_sha256!=hashlib.sha256(self.company_accounts_xml.encode('utf-8')).hexdigest()):
            raise ValueError('Accounts draft does not bind its exact current-source documents.')

    @property
    def canonical_json(self):
        raw=_canonical({'version':'annual-accounts-delivery-draft-v1','draft':self})
        if len(raw.encode('utf-8'))>32*1024*1024:raise ValueError('Accounts retained draft is too large.')
        return raw

    @property
    def sha256(self):return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()


@dataclass(frozen=True,slots=True)
class StoredAnnualAccountsDeliveryDraft:
    draft: AnnualAccountsDeliveryDraft
    recorded_at: Timestamp

    def __post_init__(self):
        if type(self.draft) is not AnnualAccountsDeliveryDraft or type(self.recorded_at) is not Timestamp:
            raise ValueError('Retained Accounts draft evidence is invalid.')


def _render(source,email,representative):
    from .public import AnnualAccountsRenderInput,build_annual_accounts,render_annual_accounts
    return render_annual_accounts(AnnualAccountsRenderInput(build_annual_accounts(_calculation_source(source)),
        source.organization_number,source.legal_name,email,_approval(source),representative))


def prepare_annual_accounts_delivery(source,*,filing_id,command_key,actor_id,contact_email,confirming_representative,schemas):
    from .public import AnnualAccountsError
    try:
        documents=_render(source,contact_email,confirming_representative)
        inspection=schemas.validate_pair(documents.main_form_xml.encode('utf-8'),documents.company_accounts_xml.encode('utf-8'),
            organization_number=source.organization_number,income_year=int(source.income_year))
        return AnnualAccountsDeliveryDraft(filing_id,command_key,actor_id,source,contact_email,confirming_representative,
            documents.main_form_xml,documents.company_accounts_xml,inspection)
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,RecursionError):raise AnnualAccountsError.invalid_input() from None


def decode_annual_accounts_delivery_draft(raw,expected_sha256):
    """Strict byte-preserving storage codec; re-rendering also detects lossy facts."""
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError()
            result[key]=value
        return result
    def constant(_):raise ValueError()
    def obj(value,keys):
        if type(value) is not dict or set(value)!=set(keys):raise ValueError()
        return value
    try:
        if (type(raw) is not str or len(raw.encode('utf-8'))>32*1024*1024
                or hashlib.sha256(raw.encode('utf-8')).hexdigest()!=expected_sha256):raise ValueError()
        root=obj(json.loads(raw,object_pairs_hook=pairs,parse_constant=constant),('version','draft'))
        if root['version']!='annual-accounts-delivery-draft-v1':raise ValueError()
        value=obj(root['draft'],('filing_id','command_key','prepared_by','source','contact_email','confirming_representative',
                               'main_form_xml','company_accounts_xml','inspection'))
        source=obj(value['source'],('company_id','income_year','organization_number','legal_name','annual_data','ledger_entries','owning_snapshots','upstream_sha256'))
        company=obj(source['company_id'],('value',));year=obj(source['income_year'],('value',))
        if type(year['value']) is not int:raise ValueError()
        actor=obj(value['prepared_by'],('kind','subject'));subject=obj(actor['subject'],('value',))
        command=obj(value['command_key'],('value',))
        inspection=obj(value['inspection'],('schema_sha256','organization_number','income_year','main_form_sha256','company_accounts_sha256'))
        source=AnnualAccountsDeliverySource(**(source|{'company_id':CompanyId(company['value']),'income_year':IncomeYear(year['value'])}))
        draft=AnnualAccountsDeliveryDraft(**(value|{'source':source,'command_key':IdempotencyKey(command['value']),
            'prepared_by':ActorId(ActorKind(actor['kind']),UserId(subject['value'])),
            'inspection':AnnualAccountsDocumentsInspection(**inspection)}))
        if draft.canonical_json!=raw:raise ValueError()
        return draft
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        raise ValueError('Retained Accounts draft is invalid or its exact bytes changed.') from None
