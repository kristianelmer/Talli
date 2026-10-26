"""Pinned, offline 2025 Tax XSD/code-list validation. No authority connection."""
from __future__ import annotations

import base64
from hashlib import sha256
import json
from pathlib import Path
import re

from lxml import etree

from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError, TaxDeliveryEnvelope, TaxDeliverySchemaValidator,
    TaxSchemaValidation, tax_delivery_schema_adapter,
    TaxCurrentDocumentResponse, TaxCurrentDocument, TaxCurrentDocumentKind,
)


_BUNDLE_SHA256 = '56668da96711b664843df91d518bb127eb79bddf93c9635765bbd28d35bdda1b'
_COMMIT = '74d9c7dd020aa4701034194630c1b16609154986'
_BUNDLE = Path(__file__).resolve().parents[1] / 'modules/company_tax_filing/schemas/2025'
_TAX_XSD = 'skattemeldingUpersonlig_v5_ekstern.xsd'
_BUSINESS_XSD = 'naeringsspesifikasjon_v6_ekstern.xsd'
_ENVELOPE_XSD = 'skattemeldingognaeringsspesifikasjonrequest_v2_kompakt.xsd'
_CURRENT_XSD = 'skattemeldingognaeringsspesifikasjonforespoerselresponse_v2_kompakt.xsd'
_TAX_NS = '{urn:no:skatteetaten:fastsetting:formueinntekt:skattemelding:upersonlig:ekstern:v5}'
_BUSINESS_NS = '{urn:no:skatteetaten:fastsetting:formueinntekt:naeringsspesifikasjon:ekstern:v6}'
_ENVELOPE_NS = '{no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:request:v2}'
_CURRENT_NS = '{no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:forespoersel:response:v2}'
_CODE_LISTS = {
    'resultatOgBalanseregnskapstype': '2025_resultatregnskapOgBalanse.xml',
    'permanentForskjellstype': '2025_permanentForskjellstype.xml',
    'regnskapspliktstype': '2025_regnskapsplikttype.xml',
    'virksomhetstype': '2025_virksomhetstype.xml',
    'regeltypeForAarsregnskap': '2025_regeltypeForAarsregnskap.xml',
}
_FILES = {_TAX_XSD, _BUSINESS_XSD, _ENVELOPE_XSD, _CURRENT_XSD, *_CODE_LISTS.values(), 'LICENSE'}
_RESULT_FAMILIES = frozenset({'balanseverdiForAnleggsmiddel', 'balanseverdiForOmloepsmiddel',
    'kortsiktigGjeld', 'egenkapital', 'annenDriftskostnad', 'finansinntekt', 'finanskostnad'})
_CURRENT_TAX_LEAVES = frozenset({'partsnummer','inntektsaar',
    'inntektOgUnderskudd/inntekt/naeringsinntekt/beloepSomHeltall',
    'inntektOgUnderskudd/inntektsfradrag/underskudd/beloepSomHeltall',
    'spesifikasjonAvForholdRelevanteForBeskatning/aksjeIAksjonaerregisteret/id',
    'spesifikasjonAvForholdRelevanteForBeskatning/aksjeIAksjonaerregisteret/erOmfattetAvFritaksmetoden/boolsk',
    'spesifikasjonAvForholdRelevanteForBeskatning/aksjeIAksjonaerregisteret/utbytte/beloepSomHeltall'})
_CURRENT_TAX_PATHS = frozenset('/'.join(path.split('/')[:n])
    for path in _CURRENT_TAX_LEAVES for n in range(1,len(path.split('/'))+1))


class _DenyExternalResources(etree.Resolver):
    def resolve(self, url, public_id, context):
        raise ValueError('External XML resources are forbidden.')


def _parse(raw):
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True,
        huge_tree=False, recover=False, remove_comments=True, remove_pis=True)
    parser.resolvers.add(_DenyExternalResources())
    root = etree.fromstring(raw, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError('Document type declarations are forbidden.')
    return root


def _supported_current_tax(root):
    def visit(node,path):
        allowed_attributes = {'{http://www.w3.org/2001/XMLSchema-instance}schemaLocation'} if not path else set()
        if set(node.attrib)-allowed_attributes:
            raise CompanyTaxError.current_return_unsupported()
        for child in node:
            child_path=path+('/' if path else '')+etree.QName(child).localname
            if child_path not in _CURRENT_TAX_PATHS:
                raise CompanyTaxError.current_return_unsupported()
            visit(child,child_path)
    visit(root,'')


def _current_register_facts(root):
    rows={}
    for node in root.findall(_TAX_NS+'spesifikasjonAvForholdRelevanteForBeskatning/'+_TAX_NS+'aksjeIAksjonaerregisteret'):
        identity=node.findtext(_TAX_NS+'id')
        if not identity or identity in rows:
            raise CompanyTaxError.current_return_unsupported()
        exemption=node.findtext(_TAX_NS+'erOmfattetAvFritaksmetoden/'+_TAX_NS+'boolsk')
        dividend=node.findtext(_TAX_NS+'utbytte/'+_TAX_NS+'beloepSomHeltall')
        rows[identity]=(None if exemption is None else exemption in ('true','1'),
            None if dividend is None else int(dividend))
    return rows


@tax_delivery_schema_adapter(TaxDeliverySchemaValidator)
class PinnedTax2025Schemas:
    """Use packaged bytes verified against one fixed upstream commit.

    No runtime download, caller-selected schema, filesystem resolver, DTD or
    network lookup is available. Successful validation proves local structure,
    code-list membership and exact envelope binding, not authority acceptance.
    """
    def __init__(self):
        try:
            manifest_raw = (_BUNDLE/'manifest.json').read_bytes()
            if sha256(manifest_raw).hexdigest() != _BUNDLE_SHA256:
                raise ValueError('Schema manifest integrity failed.')
            manifest = json.loads(manifest_raw)
            if (manifest['sourceCommit'] != _COMMIT or manifest['incomeYear'] != 2025
                    or set(manifest['files']) != _FILES):
                raise ValueError('Schema generation is unsupported.')
            contents = {}
            for name, expected in manifest['files'].items():
                path = _BUNDLE/name
                if path.is_symlink():
                    raise ValueError('Schema resources cannot be links.')
                raw = path.read_bytes()
                if len(raw) != expected['bytes'] or sha256(raw).hexdigest() != expected['sha256']:
                    raise ValueError('Schema resource integrity failed.')
                contents[name] = raw
            self._schemas = tuple(etree.XMLSchema(_parse(contents[name]))
                for name in (_TAX_XSD, _BUSINESS_XSD, _ENVELOPE_XSD))
            self._current_schema = etree.XMLSchema(_parse(contents[_CURRENT_XSD]))
            self._codes = {tag: frozenset(node.text for node in
                _parse(contents[name]).findall('.//{*}kode/{*}tekniskNavn'))
                for tag, name in _CODE_LISTS.items()}
            if any(not values for values in self._codes.values()):
                raise ValueError('Schema code-list coverage is missing.')
            self._result_codes = {node.findtext('{*}tekniskNavn'):
                frozenset(code.findtext('{*}tekniskNavn') for code in node.findall('{*}kode'))
                for node in _parse(contents[_CODE_LISTS['resultatOgBalanseregnskapstype']]).findall('.//{*}underkodeliste')
                if node.findtext('{*}tekniskNavn') in _RESULT_FAMILIES}
            if set(self._result_codes) != _RESULT_FAMILIES:
                raise ValueError('Supported result/balance code families are incomplete.')
        except (OSError, ValueError, TypeError, KeyError, etree.LxmlError):
            raise CompanyTaxError.unavailable() from None

    @property
    def schema_sha256(self):
        return _BUNDLE_SHA256

    def inspect_current(self, response: TaxCurrentDocumentResponse) -> TaxCurrentDocument:
        """Inspect the original response, retaining all bytes before parsing.

        Unhandled locked, guidance or existing business facts cannot disappear
        when a new complete delivery is generated from the owning ledgers.
        """
        return self._inspect_current(response)[0]

    def _inspect_current(self, response):
        try:
            if type(response) is not TaxCurrentDocumentResponse:
                raise ValueError('Current Tax response type is invalid.')
            raw = response.raw_bytes
            raw.decode('utf-8',errors='strict')
            root = _parse(raw)
            self._current_schema.assertValid(root)
            if root.getroottree().docinfo.encoding.upper().replace('-','') != 'UTF8':
                raise ValueError('Current Tax response encoding is unsupported.')
            documents = root.find(_CURRENT_NS+'dokumenter')
            if documents is None:
                raise ValueError('Current Tax document is missing.')
            locked = root.find(_CURRENT_NS+'laasteFelt')
            if ((locked is not None and len(locked))
                    or documents.find(_CURRENT_NS+'utvidetVeiledningdokument') is not None
                    or documents.find(_CURRENT_NS+'naeringsspesifikasjondokument') is not None):
                raise CompanyTaxError.current_return_unsupported()
            node = documents.find(_CURRENT_NS+'skattemeldingdokument')
            if node is None:
                raise ValueError('Current Tax document is missing.')
            reference = node.findtext(_CURRENT_NS+'id') or ''
            if reference != reference.strip():
                raise ValueError('Current Tax document reference is ambiguous.')
            kind = TaxCurrentDocumentKind(node.findtext(_CURRENT_NS+'type'))
            if node.findtext(_CURRENT_NS+'encoding') != 'utf-8':
                raise ValueError('Current Tax document encoding is unsupported.')
            encoded = re.sub(r'[\t\n\r ]+','',node.findtext(_CURRENT_NS+'content') or '')
            tax_bytes = base64.b64decode(encoded,validate=True)
            tax_bytes.decode('utf-8',errors='strict')
            tax = _parse(tax_bytes)
            if tax.getroottree().docinfo.encoding.upper().replace('-','') != 'UTF8':
                raise ValueError('Current Tax document encoding is unsupported.')
            self._schemas[0].assertValid(tax)
            if tax.findtext(_TAX_NS+'inntektsaar') != str(int(response.income_year)):
                raise ValueError('Current Tax document year mismatches the requested scope.')
            _supported_current_tax(tax)
            party = tax.findtext(_TAX_NS+'partsnummer') or ''
            return TaxCurrentDocument(response,reference,party,kind,sha256(tax_bytes).hexdigest(),self.schema_sha256), tax
        except CompanyTaxError:
            raise
        except (ValueError, TypeError, AttributeError, etree.LxmlError):
            raise CompanyTaxError.unavailable() from None

    def validate(self, envelope: TaxDeliveryEnvelope, *, current_document: TaxCurrentDocument | None = None) -> TaxSchemaValidation:
        try:
            if not isinstance(envelope, TaxDeliveryEnvelope) or envelope.schema_sha256 != self.schema_sha256:
                raise ValueError('Tax documents use a different schema pin.')
            raw = tuple(value.encode('utf-8') for value in
                (envelope.tax_xml, envelope.business_xml, envelope.envelope_xml))
            documents = tuple(_parse(value) for value in raw)
            for schema, root in zip(self._schemas, documents):
                schema.assertValid(root)
            tax, business, request = documents
            if current_document is not None:
                if type(current_document) is not TaxCurrentDocument:
                    raise ValueError('Current Tax document type is invalid.')
                inspected,original=self._inspect_current(current_document.response)
                if (inspected!=current_document or inspected.schema_sha256!=envelope.schema_sha256
                        or inspected.document_reference!=envelope.current_document_reference
                        or inspected.response.organization_number!=envelope.source.organization_number
                        or inspected.response.income_year!=envelope.source.income_year
                        or inspected.party_number!=tax.findtext(_TAX_NS+'partsnummer')):
                    raise ValueError('Current Tax original does not bind this delivery.')
                generated=_current_register_facts(tax)
                if any(generated.get(identity)!=facts for identity,facts in _current_register_facts(original).items()):
                    raise CompanyTaxError.current_return_unsupported()
            year = str(int(envelope.source.income_year))
            if (year != '2025' or tax.findtext(_TAX_NS+'inntektsaar') != year
                    or business.findtext(_BUSINESS_NS+'inntektsaar') != year
                    or request.findtext(_ENVELOPE_NS+'inntektsaar') != year
                    or tax.findtext(_TAX_NS+'partsnummer') != business.findtext(_BUSINESS_NS+'partsreferanse')
                    or request.findtext(_ENVELOPE_NS+'innsendingsinformasjon/'+_ENVELOPE_NS+'tin') != envelope.source.organization_number
                    or request.findtext(_ENVELOPE_NS+'innsendingsinformasjon/'+_ENVELOPE_NS+'innsendingstype') != 'komplett'
                    or request.findtext(_ENVELOPE_NS+'innsendingsinformasjon/'+_ENVELOPE_NS+'innsendingsformaal') != 'egenfastsetting'
                    or request.findtext(_ENVELOPE_NS+'dokumentreferanseTilGjeldendeDokument/'+_ENVELOPE_NS+'dokumenttype') != 'skattemeldingUpersonlig'
                    or request.findtext(_ENVELOPE_NS+'dokumentreferanseTilGjeldendeDokument/'+_ENVELOPE_NS+'dokumentidentifikator') != envelope.current_document_reference):
                raise ValueError('Tax documents have inconsistent company/year/current-reference bindings.')
            enclosed = request.findall(_ENVELOPE_NS+'dokumenter/'+_ENVELOPE_NS+'dokument')
            if len(enclosed) != 2:
                raise ValueError('Tax requires exactly two statutory documents.')
            for node, kind, expected in zip(enclosed,
                    ('skattemeldingUpersonlig', 'naeringsspesifikasjon'), raw[:2]):
                if (node.findtext(_ENVELOPE_NS+'type') != kind
                        or node.findtext(_ENVELOPE_NS+'encoding') != 'utf-8'
                        or base64.b64decode(node.findtext(_ENVELOPE_NS+'content') or '', validate=True) != expected):
                    raise ValueError('Tax envelope does not contain the exact reviewed document bytes.')
            for name, allowed in self._codes.items():
                for node in business.iter(_BUSINESS_NS+name):
                    if len(node) == 0 and node.text not in allowed:
                        raise ValueError('Tax business document uses a code outside the pinned list.')
                    if name == 'resultatOgBalanseregnskapstype' and len(node) == 0:
                        family = next((etree.QName(parent).localname for parent in node.iterancestors()
                            if etree.QName(parent).localname in _RESULT_FAMILIES), None)
                        if family is None or node.text not in self._result_codes[family]:
                            raise ValueError('Tax result/balance code is outside its occurrence category.')
            proof = TaxSchemaValidation(self.schema_sha256, envelope.source.source_sha256,
                envelope.review_sha256, *(sha256(value).hexdigest() for value in raw))
            proof.verify(envelope)
            return proof
        except (ValueError, TypeError, AttributeError, etree.LxmlError):
            # Do not disclose XML, source values, parser paths or parser logs.
            raise CompanyTaxError.invalid_input() from None
