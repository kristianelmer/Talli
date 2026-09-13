"""Binary64 rules retained from the released Company Tax calculations."""
from __future__ import annotations

import math
from collections.abc import Iterable


def number(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return 0.0
        if value.startswith(('0x', '0X', '0b', '0B', '0o', '0O')):
            try:
                return float(int(value, 0))
            except ValueError:
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
