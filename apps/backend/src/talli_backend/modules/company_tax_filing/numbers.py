"""Binary64 rules retained from the released Company Tax calculations."""
from __future__ import annotations

import math
import re
from collections.abc import Iterable

_SPACE = '\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def _array_text(values) -> str:
    return ','.join('' if value is None else _array_text(value) if isinstance(value, (list, tuple))
                    else text(value) if isinstance(value, (str, int, float, bool)) else '[object Object]'
                    for value in values)


def truthy(value: object) -> bool:
    """ECMAScript Boolean conversion; empty arrays and objects remain true."""
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, (int, float)):
        return value != 0 and not (isinstance(value, float) and math.isnan(value))
    return True


def number(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (list, tuple)):
        value = _array_text(value)
    if isinstance(value, str):
        value = value.strip(_SPACE)
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
    except (TypeError, ValueError, OverflowError):
        return math.nan


def total(values: Iterable[float]) -> float:
    # Python 3.12 sum uses compensated summation; the released JS reduce does not.
    result = 0.0
    for value in values:
        result += value
    return result


def rounded(value: float) -> float:
    if not math.isfinite(value):
        return value
    integral = math.floor(value)
    return float(integral + (value - integral >= 0.5))


def money(value: float) -> float:
    return rounded(value * 100) / 100


def nonnegative(value: float) -> float:
    return value if math.isnan(value) else max(0.0, value)


def text(value: str | float | int | bool) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return 'true' if value else 'false'
    value = float(value)
    if math.isnan(value):
        return 'NaN'
    if math.isinf(value):
        return 'Infinity' if value > 0 else '-Infinity'
    if value == 0:
        return '0'
    rendered = repr(value)
    if 1e-6 <= abs(value) < 1e21:
        from decimal import Decimal
        fixed = format(Decimal(rendered), 'f')
        return fixed.rstrip('0').rstrip('.') if '.' in fixed else fixed
    mantissa, exponent = rendered.split('e')
    return f'{mantissa.removesuffix(".0")}e{int(exponent):+d}'
