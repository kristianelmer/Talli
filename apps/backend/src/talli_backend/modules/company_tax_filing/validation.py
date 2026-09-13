"""Bounded official validation presentation with the released Norwegian order."""
from __future__ import annotations

import re

from icu import Collator, Locale

from .rendering import _SPACE, required_xml


def _safe_string(value: str) -> str:
    value = re.sub(r'[\x00-\x1f\x7f]', ' ', value)
    value = re.sub(f'[{_SPACE}]+', ' ', value).strip(' ')
    # Preserve JS slice(0, 500), which counts UTF-16 units rather than code points.
    return value.encode('utf-16-le', 'surrogatepass')[:1000].decode('utf-16-le', 'surrogatepass')


def _values(xml: str, element: str) -> list[str]:
    name = rf'(?:[A-Za-z_][\w.-]*:)?{element}'
    return [value for match in re.finditer(rf'<{name}\b[^>]*>([^<]*)</{name}>', xml, re.ASCII)
            if (value := _safe_string(match[1]))]


def summarize(value: str):
    xml = required_xml(value, 'Company tax validation result')
    results = _values(xml, 'resultatAvValidering')
    result = results[0] if results else None
    collator = Collator.createInstance(Locale('nb'))

    def ordered(element):
        # Keep insertion order when distinct strings compare equally in ICU.
        return sorted(dict.fromkeys(_values(xml, element)), key=collator.getSortKey)

    return {'result': result if result in ('validertOK', 'validertMedFeil') else 'unknown',
            'deviationCodes': ordered('avvikstype'), 'guidanceCodes': ordered('veiledningstype'),
            'failureReasons': ordered('aarsakTilValidertMedFeil')}
