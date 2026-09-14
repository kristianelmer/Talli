"""Ordered Company Tax XML and validation/submission envelopes; no I/O."""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field

from .numbers import text

_SPACE = '\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'
_DOCUMENTS = {
    'skattemeldingUpersonlig': ('skattemelding', 'urn:no:skatteetaten:fastsetting:formueinntekt:skattemelding:upersonlig:ekstern:v5'),
    'naeringsspesifikasjon': ('naeringsspesifikasjon', 'urn:no:skatteetaten:fastsetting:formueinntekt:naeringsspesifikasjon:ekstern:v6'),
}


def _escape(value: str) -> str:
    return value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;')


@dataclass
class _Node:
    name: str
    children: dict[str, _Node] = field(default_factory=dict)
    value: str | float | int | bool | None = None


def _render(node: _Node, depth: int, namespace: str = '') -> str:
    indentation = '  ' * depth
    attribute = f' xmlns="{namespace}"' if namespace else ''
    opening = f'{indentation}<{node.name}{attribute}'
    if node.value is not None:
        return f'{opening}>{_escape(text(node.value))}</{node.name}>'
    children = '\n'.join(_render(child, depth + 1) for child in node.children.values())
    return f'{opening}>\n{children}\n{indentation}</{node.name}>' if children else f'{opening}/>'


def _document(document, fields):
    name, namespace = _DOCUMENTS[document]
    root = _Node(name)
    for item in fields:
        if item['authorityDocument'] != document:
            continue
        path = item['path']
        if not path.strip(_SPACE):
            raise ValueError('XML-felt mangler sti.')
        segments = []
        for raw in path.split('.'):
            match = re.fullmatch(r'([A-Za-z][A-Za-z0-9]*)(?:\[([0-9]+)\])?', raw)
            if not match:
                raise ValueError(f'Ugyldig XML-feltsti: {path}')
            node_name, index = match.groups()
            segments.append((node_name, node_name if index is None else f'{node_name}[{int(index)}]'))
        if segments[0][0] == name:
            segments.pop(0)
        if not segments:
            raise ValueError(f'XML-felt mangler sti under {name}.')
        node = root
        for index, (node_name, key) in enumerate(segments):
            child = node.children.setdefault(key, _Node(node_name))
            if index == len(segments) - 1:
                if child.children or child.value is not None:
                    raise ValueError(f'XML-felt er duplisert: {key}')
                child.value = item['value']
            elif child.value is not None:
                raise ValueError(f'XML-felt brukes både som verdi og gruppe: {key}')
            node = child
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + _render(root, 0, namespace) + '\n'


def render(fields):
    return {'skattemeldingXml': _document('skattemeldingUpersonlig', fields),
            'naeringsspesifikasjonXml': _document('naeringsspesifikasjon', fields)}


def required_xml(value: str, label: str) -> str:
    if not value or not value.lstrip(_SPACE).startswith('<'):
        raise ValueError(f'{label} XML is required.')
    return value


def _utf8(value: str) -> bytes:
    # Buffer.from replaces unpaired UTF-16 surrogates with U+FFFD.
    return value.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace').encode('utf-8')


def _length(value: str) -> int:
    return len(value.encode('utf-16-le', 'surrogatepass')) // 2


def envelope(input):
    tax = required_xml(input['skattemeldingXml'], 'Company tax return')
    business = required_xml(input['naeringsspesifikasjonXml'], 'Company tax business specification')
    reference = (input.get('currentDocumentReference') or '').strip(_SPACE)
    if _length(reference) > 4000:
        raise ValueError('Current company tax document reference is too long.')
    if 'currentDocumentReference' in input and not reference:
        raise ValueError('Current company tax document reference is required.')
    creator = input['createdBy'].strip(_SPACE)
    if not creator or _length(creator) > 4000:
        raise ValueError('Company tax creator name is required.')
    org, year = input['companyOrgNumber'], input['incomeYear']
    if not re.fullmatch(r'[0-9]{9}', org):
        raise ValueError('Company tax organization number must contain 9 digits.')
    if isinstance(year, bool) or not isinstance(year, (int, float)) or not 2000 <= year <= 2100 or int(year) != year:
        raise ValueError('Company tax income year must be an integer between 2000 and 2100.')
    reference_lines = [
        '  <dokumentreferanseTilGjeldendeDokument>',
        '    <dokumenttype>skattemeldingUpersonlig</dokumenttype>',
        f'    <dokumentidentifikator>{_escape(reference)}</dokumentidentifikator>',
        '  </dokumentreferanseTilGjeldendeDokument>',
    ] if reference else []
    return '\n'.join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<skattemeldingOgNaeringsspesifikasjonRequest xmlns="no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:request:v2">',
        '  <dokumenter>', '    <dokument>', '      <type>skattemeldingUpersonlig</type>',
        '      <encoding>utf-8</encoding>', f'      <content>{base64.b64encode(_utf8(tax)).decode("ascii")}</content>',
        '    </dokument>', '    <dokument>', '      <type>naeringsspesifikasjon</type>',
        '      <encoding>utf-8</encoding>', f'      <content>{base64.b64encode(_utf8(business)).decode("ascii")}</content>',
        '    </dokument>', '  </dokumenter>', *reference_lines,
        f'  <inntektsaar>{int(year)}</inntektsaar>', '  <innsendingsinformasjon>',
        '    <innsendingstype>komplett</innsendingstype>', f'    <opprettetAv>{_escape(creator)}</opprettetAv>',
        f'    <tin>{org}</tin>', '    <innsendingsformaal>egenfastsetting</innsendingsformaal>',
        '  </innsendingsinformasjon>', '</skattemeldingOgNaeringsspesifikasjonRequest>', '',
    ])
