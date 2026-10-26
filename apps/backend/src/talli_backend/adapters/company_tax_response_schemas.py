"""Pinned offline validation-response XSD; separate from delivery review hashes."""
from __future__ import annotations

import base64
from hashlib import sha256
import json
from pathlib import Path
import re

from lxml import etree

from talli_backend.adapters.company_tax_xml import _parse
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose,
    TaxValidationCalculatedDocument,TaxValidationResponseInspection,TaxValidationResultCode,
    TaxValidationResponseValidator,tax_delivery_schema_adapter,
)

_BUNDLE=Path(__file__).resolve().parents[1]/'modules/company_tax_filing/schemas/validation-v2'
_BUNDLE_SHA256='eaeabcebee3915f31113f026a1d7f854343670c2f45a584691213668d18a71a1'
_COMMIT='74d9c7dd020aa4701034194630c1b16609154986'
_XSD='skattemeldingognaeringsspesifikasjonresponse_v2.xsd'
_NS='{no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:response:v2}'


@tax_delivery_schema_adapter(TaxValidationResponseValidator)
class PinnedTaxValidationResponseSchemas:
    def __init__(self):
        try:
            if _BUNDLE.is_symlink():raise ValueError('Tax schema bundle cannot be a link.')
            path=_BUNDLE/'manifest.json'
            if path.is_symlink():raise ValueError('Tax schema manifest cannot be a link.')
            raw=path.read_bytes()
            if sha256(raw).hexdigest()!=_BUNDLE_SHA256:raise ValueError('Tax response schema pin changed.')
            manifest=json.loads(raw)
            if (manifest['version']!='company-tax-validation-response-schemas-v1'
                    or manifest['sourceCommit']!=_COMMIT or manifest['responseVersion']!='v2'
                    or set(manifest['files'])!={_XSD,'LICENSE'}):raise ValueError('Tax response schema generation is unsupported.')
            contents={}
            for name,expected in manifest['files'].items():
                path=_BUNDLE/name
                if path.is_symlink():raise ValueError('Tax schema resource cannot be a link.')
                raw=path.read_bytes()
                if len(raw)!=expected['bytes'] or sha256(raw).hexdigest()!=expected['sha256']:
                    raise ValueError('Tax response schema resource changed.')
                contents[name]=raw
            self._schema=etree.XMLSchema(_parse(contents[_XSD]))
        except (OSError,ValueError,TypeError,KeyError,etree.LxmlError):
            raise CompanyTaxError.unavailable() from None

    @property
    def schema_sha256(self) -> str:return _BUNDLE_SHA256

    def inspect(self,original: TaxDeliveryReadOriginal) -> TaxValidationResponseInspection:
        try:
            if (type(original) is not TaxDeliveryReadOriginal
                    or original.purpose is not TaxDeliveryOriginalPurpose.VALIDATION_RESULT):raise ValueError()
            root=_parse(original.raw_bytes)
            if root.getroottree().docinfo.encoding.upper().replace('-','')!='UTF8':raise ValueError()
            self._schema.assertValid(root)
            documents=[]
            for node in root.findall(_NS+'dokumenter/'+_NS+'dokument'):
                if node.findtext(_NS+'encoding')!='utf-8':raise ValueError()
                encoded=re.sub(r'[\t\n\r ]+','',node.findtext(_NS+'content') or '')
                raw=base64.b64decode(encoded,validate=True)
                documents.append(TaxValidationCalculatedDocument(node.findtext(_NS+'type'),base64.b64encode(raw).decode('ascii')))
            result=TaxValidationResponseInspection(self.schema_sha256,original.sha256,
                TaxValidationResultCode(root.findtext(_NS+'resultatAvValidering')),
                len(root.findall(_NS+'avvikEtterBeregning/'+_NS+'avvik')),
                len(root.findall(_NS+'avvikVedValidering/'+_NS+'avvik')),
                len(root.findall(_NS+'veiledningEtterKontroll/'+_NS+'veiledning')),
                len(root.findall(_NS+'aarsakTilValidertMedFeil')),tuple(documents))
            result.verify_original(original)
            return result
        except (ValueError,TypeError,AttributeError,etree.LxmlError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
