"""Evidence-only Accounts workspace and access-controlled exact originals."""
from dataclasses import dataclass
import base64
import hashlib
import json
from xml.etree import ElementTree

from talli_backend.application.annual_accounts_delivery_source import read_annual_accounts_delivery_source
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsError,project_annual_accounts_source,AnnualAccountsDeliveryIntent as Intent,
    AnnualAccountsDeliveryObservation as Observation,AnnualAccountsDeliveryStage as Stage,AnnualAccountsFrameKind as Kind,
)


@dataclass(frozen=True,slots=True)
class AccountsDeliveryOriginal:
    key: str
    purpose: str
    source_filing_id: str
    sha256: str
    media_type: str
    body_base64: str


def delivery_originals(stored,events):
    draft=stored.draft
    def original(key,purpose,raw,media):
        return AccountsDeliveryOriginal(key,purpose,draft.filing_id,hashlib.sha256(raw).hexdigest(),media,base64.b64encode(raw).decode())
    source=json.dumps(json.loads(draft.canonical_json)['draft']['source'],sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    if hashlib.sha256(source).hexdigest()!=draft.source.sha256:raise AnnualAccountsError.unavailable()
    result=[original('draft:'+draft.sha256,'prepared_draft',draft.canonical_json.encode(),'application/json'),
        original('source:'+draft.source.sha256,'prepared_source',source,'application/json'),
        original('prepared_main:'+draft.inspection.main_form_sha256,'prepared_main',draft.main_form_xml.encode(),'application/xml'),
        original('prepared_accounts:'+draft.inspection.company_accounts_sha256,'prepared_accounts',draft.company_accounts_xml.encode(),'application/xml')]
    for row in events:
        result.append(original('event:'+row.record.sha256,'operation_record',row.record.canonical_json.encode(),'application/json'))
        if type(row.record) is Observation and row.record.original.body_base64 is not None:
            value=row.record.original
            result.append(original('original:'+row.record.sha256,value.purpose.value,value.raw_bytes,value.content_type or 'application/octet-stream'))
    return tuple(result)


def document_fields(draft):
    result=[]
    for name,raw in (('Hovedskjema',draft.main_form_xml),('Underskjema',draft.company_accounts_xml)):
        root=ElementTree.fromstring(raw);pending=[(root,'/'+root.tag)]
        while pending:
            node,path=pending.pop()
            if node.text is not None and node.text.strip() or len(node)==0:
                result.append({'document':name,'path':path,'value':node.text or ''})
            result.extend({'document':name,'path':path+'/@'+key,'value':value} for key,value in sorted(node.attrib.items()))
            children=list(node);counts={};indexed=[]
            for child in children:
                counts[child.tag]=counts.get(child.tag,0)+1;indexed.append((child,path+'/'+child.tag+'['+str(counts[child.tag])+']'))
            pending.extend(reversed(indexed))
            if len(result)>100000:raise AnnualAccountsError.unavailable()
    return result


class AnnualAccountsDeliveryWorkspace:
    def __init__(self,workflow):self._workflow=workflow

    async def _snapshot(self,session,query):
        if session.actor_id!=query.actor_id:raise AnnualAccountsError.forbidden()
        async with session.transaction(snapshot=True) as transaction:
            snapshot=await transaction.filing_source_snapshot(query);facts=project_annual_accounts_source(query,snapshot)
        if snapshot.contract_version!='annual-accounts-source-v3' or facts.history_coverage.status!='complete':raise AnnualAccountsError.unavailable()
        return snapshot

    async def original(self,session,query,filing_id,key):
        # Archive access depends on current owner/MFA and complete stored
        # enumeration, independently of financial source, lease or schema I/O.
        snapshot=await self._snapshot(session,query)
        stored=next((row for row in snapshot.delivery_drafts if row.draft.filing_id==filing_id),None)
        if stored is None:raise AnnualAccountsError.not_found()
        events=tuple(row for row in snapshot.delivery_events if row.record.binding.filing_id==filing_id)
        matches=[row for row in delivery_originals(stored,events) if row.key==key]
        if len(matches)!=1:raise AnnualAccountsError.not_found()
        return matches[0]

    async def read(self,session,query,*,correlation_id):
        if session.actor_id!=query.actor_id:raise AnnualAccountsError.forbidden()
        workflow=self._workflow
        async with session.transaction(snapshot=True) as transaction:
            snapshot=await transaction.filing_source_snapshot(query);facts=project_annual_accounts_source(query,snapshot)
            if snapshot.contract_version!='annual-accounts-source-v3' or facts.history_coverage.status!='complete':raise AnnualAccountsError.unavailable()
            try:current=await read_annual_accounts_delivery_source(transaction,query,corporate=workflow._corporate,correlation_id=correlation_id)
            except AnnualAccountsError:current=None
        ports=workflow._ports;configured=ports is not None and ports.available(session,query.company_id,query.income_year)
        operations=snapshot.coverage.get('deliveryOperationsEnabled') is True;rows=[]
        for stored in snapshot.delivery_drafts:
            draft=stored.draft;events=tuple(row for row in snapshot.delivery_events if row.record.binding.filing_id==draft.filing_id)
            try:
                workflow._validate_draft(draft)
                state=workflow._inspect(stored,events,{str(row.sequence):snapshot.coverage['deliveryEventDigests'][str(row.sequence)] for row in events})
            except AnnualAccountsError:state=None
            same=current==draft.source;actions=[];review_sha=draft.sha256;review_stage=Stage.PREPARE
            if state is not None and state.inspection.state=='confirmation_review':review_stage=Stage.CONFIRM
            elif state is not None and state.inspection.state=='person_review':review_stage=Stage.SIGN
            if review_stage is not Stage.PREPARE:
                _,frame=workflow._frame(state,Kind.UPLOAD_REVIEW if review_stage is Stage.CONFIRM else Kind.SIGN_REVIEW)
                review_sha=frame.review_sha256
            # These actions are current composition/source hints, never durable
            # permission flags. Every command repeats all owning/SQL checks.
            if state is not None and configured and same and operations and draft.prepared_by==query.actor_id and state.inspection.next_action is not None:
                action=state.inspection.next_action;stage=Stage.CONFIRM if action.value=='confirm' else Stage.SIGN if action.value=='sign' else Stage.PREPARE
                approval=state.slot('review:'+stage.value)
                if approval is None:actions.append('review_'+stage.value)
                elif approval.record.reviewed_evidence_sha256==review_sha and workflow.mutation_available(session,state,stage):actions.append(action.value)
            if state is not None and configured and draft.prepared_by==query.actor_id and workflow.reconciliation_available(session,state):actions.append('reconcile')
            issues=[]
            for kind in ((Kind.UPLOAD_REVIEW,Kind.SIGN_REVIEW) if state is not None else ()):
                _,frame=workflow._frame(state,kind)
                if frame is not None:issues=list(frame.validation_issues)
            rows.append({'filing_id':draft.filing_id,'recorded_at':stored.recorded_at.value,'draft_sha256':draft.sha256,
                'source_sha256':draft.source.sha256,'review_sha256':review_sha,'review_stage':review_stage.value,
                'state':state.inspection.state if state is not None else 'inspection_unavailable',
                'known_instance':state.inspection.known_instance if state is not None else None,'source_current':same,
                'actions':actions,'fields':document_fields(draft),'validation_issues':issues,
                'originals':[{name:getattr(item,name) for name in ('key','purpose','source_filing_id','sha256','media_type')}
                    for item in delivery_originals(stored,events)]})
        attempted=any(type(row.record) is Intent for row in snapshot.delivery_events)
        return {'version':'annual-accounts-delivery-workspace-v1','company_id':str(query.company_id),'income_year':int(query.income_year),
            'source_sha256':current.sha256 if current is not None else None,'observed_at':snapshot.as_of.value,
            'preparation_available':bool(configured and current is not None and not attempted and all(row['state']!='inspection_unavailable' for row in rows)
                and snapshot.coverage.get('deliveryDraftWritesEnabled') is True),
            'rows':rows}
