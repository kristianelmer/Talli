"""The retained offline RF simulation plan; it has no persistence or authority I/O.

Input coercion, Python codepoint ordering and strict UTF-8 hashing preserve the
original root CLI contract. They are distinct from persisted JS payload identity.
"""
from __future__ import annotations
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid5, NAMESPACE_URL

from .public import Rf1086OfflineSimulationInput,Rf1086OfflineSimulationCall,Rf1086OfflineSimulationResult


def parse_offline_simulation_input(value: Mapping[str, object]) -> Rf1086OfflineSimulationInput:
    if not value.get('authority_confirmed'):
        raise ValueError('authority confirmation is required before simulated submission')
    if not value.get('preview_confirmed'):
        raise ValueError('final preview confirmation is required before simulated submission')
    subdocuments = value.get('underskjema_xml') or {}
    if not isinstance(subdocuments, dict):
        raise ValueError('underskjema_xml must be an object')
    # Keep original evaluation/coercion order so malformed input errors retain
    # the same identity, without passing raw JSON into the production surface.
    filing = str(value['filing']); company_id = str(value['company_id']); income_year = int(value['income_year'])
    user_id = str(value['user_id']); preview_id = str(value['preview_id'])
    return Rf1086OfflineSimulationInput(filing,company_id,income_year,user_id,preview_id,
        str(value['hovedskjema_xml']),{name:str(xml) for name,xml in subdocuments.items()})


def simulate_offline_submission(input: Rf1086OfflineSimulationInput, *, clock: Callable[[], datetime] | None = None) -> Rf1086OfflineSimulationResult:
    now = clock if clock is not None else lambda: datetime.now(timezone.utc)
    authority_at = now(); preview_at = now()
    calls = []
    def record(endpoint, body):
        payload = json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False)
        body_hash = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        if any(call.endpoint == endpoint and call.body_hash == body_hash for call in calls):return
        raw = f'{input.company_id}:{input.income_year}:{input.filing}:{endpoint}:{body_hash}'
        calls.append(Rf1086OfflineSimulationCall(endpoint,body_hash,str(uuid5(NAMESPACE_URL,raw)),'prepared',now()))
    base = f'/api/aksjonaerregister/v1/{input.income_year}'
    main_id = 'simulated-'+input.preview_id
    record(base+'/1086H',{'content_type':'application/xml','xml':input.hovedskjema_xml})
    for name,xml in sorted(input.underskjema_xml.items()):
        record(base+'/'+main_id+'/1086U',{'shareholder_id':name,'content_type':'application/xml','xml':xml})
    record(base+'/'+main_id+f'/bekreft?antall_underskjema={len(input.underskjema_xml)}',{'antall_underskjema':len(input.underskjema_xml)})
    record(base+'/forsendelser/simulated-forsendelse-'+input.preview_id+'/dokumenter?page=0&size=50',{'page':0,'size':50})
    return Rf1086OfflineSimulationResult(input.filing,input.company_id,input.income_year,'receipt_stored',
        input.user_id,authority_at,input.user_id,preview_at,tuple(calls),
        f'sim-rf1086-{input.company_id}-{input.income_year}-{input.preview_id[:8]}',('sim-feedback-'+input.preview_id[:8],))
