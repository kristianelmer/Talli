"""Bounded exact original bytes and canonical Tax authority references."""
from __future__ import annotations

import base64
import json
import re
from uuid import UUID

_MAX_BODY=8*1024*1024


def _uuid(value):
    if type(value) is not str or str(UUID(value))!=value:
        raise ValueError('Tax journal identifier is invalid.')
    return value


def _instance(value):
    if type(value) is not str or re.fullmatch(r'[0-9]{1,19}/[0-9a-f-]{36}',value) is None:
        raise ValueError('Tax journal instance is invalid.')
    _uuid(value.split('/',1)[1])
    return value


def _job(value):
    if type(value) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,255}',value) is None:
        raise ValueError('Tax validation job identity is invalid.')
    return value


def _bytes(encoded, *, allow_empty=False):
    if type(encoded) is not str or len(encoded)>12*1024*1024:
        raise ValueError('Tax journal original exceeds its limit.')
    raw=base64.b64decode(encoded,validate=True)
    if ((not raw and not allow_empty) or len(raw)>_MAX_BODY
            or base64.b64encode(raw).decode('ascii')!=encoded):
        raise ValueError('Tax journal original encoding is invalid.')
    raw.decode('utf-8',errors='strict')
    return raw

def _response_object(raw: bytes):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate Tax response key.')
            result[key]=value
        return result
    def constant(_value):raise ValueError('Nonfinite Tax response value.')
    result=json.loads(raw.decode('utf-8-sig',errors='strict'),object_pairs_hook=pairs,parse_constant=constant)
    if type(result) is not dict:raise ValueError('Tax response must be an object.')
    return result
