"""ECMAScript scalar and reduction semantics for the released Accounts profile.

This is capability-local compatibility of numeric values, not accounting policy
shared with Tax. Python's compensated sum and ties-to-even round are unsuitable.
"""
from __future__ import annotations

import math
import re

SPACE = '\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def truthy(value):
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, (int, float)):
        return value != 0 and not (isinstance(value, float) and math.isnan(value))
    return True


def text(value):
    if isinstance(value, str):
        return value
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (tuple, list)):
        return ','.join('' if item is None else text(item) for item in value)
    if not isinstance(value, (int, float)):
        return '[object Object]'
    try:
        value = float(value)
    except OverflowError:
        value = -math.inf if value < 0 else math.inf
    if math.isnan(value):
        return 'NaN'
    if math.isinf(value):
        return 'Infinity' if value > 0 else '-Infinity'
    if value == 0:
        return '0'
    if 1e-6 <= abs(value) < 1e21:
        from decimal import Decimal
        fixed = format(Decimal(repr(value)), 'f')
        return fixed.rstrip('0').rstrip('.') if '.' in fixed else fixed
    mantissa, exponent = repr(value).split('e')
    return f'{mantissa.removesuffix(".0")}e{int(exponent):+d}'


def number(value):
    if value is None:
        return 0.0
    if isinstance(value, (list, tuple)):
        value = text(value)
    if isinstance(value, str):
        value = value.strip(SPACE)
        if not value:
            return 0.0
        if re.fullmatch(r'0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+', value):
            try:
                return float(int(value, 0))
            except OverflowError:
                return math.inf
        if value in ('Infinity', '+Infinity', '-Infinity'):
            return -math.inf if value.startswith('-') else math.inf
        if not re.fullmatch(r'[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', value):
            return math.nan
    try:
        return float(value)
    except OverflowError:
        return -math.inf if value < 0 else math.inf
    except (ValueError, TypeError):
        return math.nan


def total(values):
    result = 0.0
    for value in values:
        result += value
    return result


def money(value):
    scaled = value * 100
    if not math.isfinite(scaled):
        return scaled
    if scaled == 0:
        return scaled
    integral = math.floor(scaled)
    rounded = float(integral + (scaled - integral >= 0.5))
    return math.copysign(0.0, scaled) if rounded == 0 else rounded / 100
