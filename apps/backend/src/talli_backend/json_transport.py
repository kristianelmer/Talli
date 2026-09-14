"""Iterative JSON transport for validated models containing retained opaque JSON."""
from collections.abc import Mapping
from datetime import date, datetime
import json
from uuid import UUID

from pydantic import BaseModel
from starlette.responses import Response


def json_value(value):
    """Detach immutable JSON containers without imposing a Python stack-depth limit."""
    result = [None]
    active = set()
    pending = [('visit', value, result, 0)]
    while pending:
        operation, item, parent, key = pending.pop()
        if operation == 'leave':
            active.remove(item)
            continue
        if isinstance(item, (Mapping, tuple, list)):
            if id(item) in active:
                raise ValueError('Cyclic JSON transport value.')
            active.add(id(item))
            pending.append(('leave', id(item), None, None))
        if isinstance(item, Mapping):
            copied = dict.fromkeys(item)
            parent[key] = copied
            pending.extend(('visit', child, copied, name) for name, child in item.items())
        elif isinstance(item, (tuple, list)):
            copied = [None] * len(item)
            parent[key] = copied
            pending.extend(('visit', child, copied, index) for index, child in enumerate(item))
        else:
            parent[key] = item
    return result[0]


def model_json_response(model: BaseModel) -> Response:
    """Encode an already validated wire model without Pydantic's JSON depth limit.

    Field aliases and typed datetime/UUID formatting retain normal transport
    behavior. Opaque JSON is traversed without recursively reserializing it.
    """
    fragments = []
    active = set()
    pending = [('value', model)]
    while pending:
        operation, value = pending.pop()
        if operation == 'text':
            fragments.append(value)
            continue
        if operation == 'leave':
            active.remove(value)
            continue
        if isinstance(value, (BaseModel, Mapping, tuple, list)):
            if id(value) in active:
                raise ValueError('Cyclic JSON transport value.')
            active.add(id(value))
            pending.append(('leave', id(value)))
            if isinstance(value, BaseModel):
                entries = [(field.serialization_alias or field.alias or name, getattr(value, name))
                           for name, field in type(value).model_fields.items()]
            elif isinstance(value, Mapping):
                entries = list(value.items())
            else:
                entries = None
            if entries is not None:
                fragments.append('{')
                pending.append(('text', '}'))
                for index in range(len(entries) - 1, -1, -1):
                    key, child = entries[index]
                    if not isinstance(key, str):
                        raise TypeError('JSON object keys must be strings.')
                    pending.append(('value', child))
                    pending.append(('text', json.dumps(key, ensure_ascii=False) + ':'))
                    if index:
                        pending.append(('text', ','))
            else:
                fragments.append('[')
                pending.append(('text', ']'))
                for index in range(len(value) - 1, -1, -1):
                    pending.append(('value', value[index]))
                    if index:
                        pending.append(('text', ','))
        else:
            if isinstance(value, UUID):
                value = str(value)
            elif isinstance(value, datetime):
                value = value.isoformat().replace('+00:00', 'Z')
            elif isinstance(value, date):
                value = value.isoformat()
            fragments.append(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
    return Response(''.join(fragments), media_type='application/json')
