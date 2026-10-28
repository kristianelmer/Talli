"""Stdlib-only technical progress encodings shared by recovery and ingress."""
from hashlib import sha256
import json
from typing import Mapping
from uuid import UUID

FIELDS = ('operation_id','company_id','document_id','income_year','generation',
          'content_sha256','company_generation','plan_sha256')


def progress_receipts(values: Mapping[str, object]) -> tuple[str, tuple[str, ...]]:
    payload = {name: str(UUID(str(values[name]))) if name.endswith('_id') else values[name] for name in FIELDS}
    payload['action'] = values['action']
    if payload['action'] not in {'erase','retain'} or type(payload['income_year']) is not int:
        raise ValueError('invalid progress commitment')
    raw = json.dumps(payload, sort_keys=True, separators=(',',':'), ensure_ascii=False, allow_nan=False).encode()
    current = 'document-disposition-progress-v1:' + sha256(raw).hexdigest()
    legacy_values = {**payload, **{name: UUID(payload[name]) for name in FIELDS if name.endswith('_id')}}
    legacy = 'DocumentDisposition(' + ', '.join(name+'='+repr(legacy_values[name]) for name in FIELDS) + ')'
    legacy_with_action = legacy[:-1] + ', action=' + repr(payload['action']) + ')'
    return current, (sha256((legacy+':'+payload['action']).encode()).hexdigest(),
                     sha256(legacy_with_action.encode()).hexdigest())
