"""Supported 2025 company calculation documents, pinned and inspected offline."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from talli_backend.adapters.company_tax_xml import _parse,_compile_packaged_schema
from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.adapters.company_tax_response_schemas import PinnedTaxValidationResponseSchemas
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,TaxDeliveryReadOriginal,TaxDeliveryDraft,TaxCalculatedDocumentsInspection,
    TaxCalculatedDocumentValidator,tax_delivery_schema_adapter,
    TaxCalculatedReviewField,TaxCalculatedDocumentReview,TaxCalculatedDocumentsReview,
)

_BUNDLE=Path(__file__).resolve().parents[1]/'modules/company_tax_filing/schemas/calculated-2025'
_BUNDLE_SHA256='c9631dcb56397a2e9632f9a8339d4060aa8f3ae6f58c7bf35b7cc19df5e77769'
_COMMIT='74d9c7dd020aa4701034194630c1b16609154986'
_COMPUTED_XSD='beregnetskatt_upersonlig_v6.xsd'
_SUMMARY_XSD='summertSkattegrunnlagForVisning_upersonligskattyter_v4.xsd'
_TYPE_XSD='typekatalog_v2.xsd'
_RESPONSE_NS='{no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:response:v2}'
_SUMMARY_NS='{urn:no:skatteetaten:fastsetting:formueinntekt:upersonlig:summertskattegrunnlagforvisning:v4}'
_UNSUPPORTED_REGIMES=('erOmfattetAvSaerreglerForKraftforetak','erOmfattetAvPetroleumsskatteloven',
    'erOmfattetAvRederiskatteordningen','erOmfattetAvFinansskattPaaLoennOgOverskudd','harLeveringsfritak')


@tax_delivery_schema_adapter(TaxCalculatedDocumentValidator)
class PinnedTax2025CalculatedSchemas:
    def __init__(self):
        self._delivery=PinnedTax2025Schemas()
        self._response=PinnedTaxValidationResponseSchemas()
        try:
            if _BUNDLE.is_symlink() or (_BUNDLE/'manifest.json').is_symlink():raise ValueError()
            raw=(_BUNDLE/'manifest.json').read_bytes()
            if sha256(raw).hexdigest()!=_BUNDLE_SHA256:raise ValueError()
            manifest=json.loads(raw)
            if (manifest['version']!='company-tax-calculated-2025-schemas-v1' or manifest['incomeYear']!=2025
                    or manifest['sourceCommit']!=_COMMIT or set(manifest['files'])!={_COMPUTED_XSD,_SUMMARY_XSD,_TYPE_XSD,'LICENSE'}
                    or manifest['dependencies']!={'deliverySchemaSha256':self._delivery.schema_sha256,
                        'responseSchemaSha256':self._response.schema_sha256}):raise ValueError()
            contents={}
            for name,expected in manifest['files'].items():
                path=_BUNDLE/name
                if path.is_symlink():raise ValueError()
                raw=path.read_bytes()
                if len(raw)!=expected['bytes'] or sha256(raw).hexdigest()!=expected['sha256']:raise ValueError()
                contents[name]=raw
            resources={'typekatalog/typekatalog_v2.xsd':contents[_TYPE_XSD]}
            self._optional_schemas={kind:_compile_packaged_schema(contents[name],resources) for kind,name in (
                ('beregnetSkattUpersonlig',_COMPUTED_XSD),('summertSkattegrunnlagForVisningUpersonlig',_SUMMARY_XSD))}
        except (OSError,ValueError,TypeError,KeyError,etree.LxmlError):
            raise CompanyTaxError.unavailable() from None

    @property
    def schema_sha256(self) -> str:return _BUNDLE_SHA256

    def inspect(self,original: TaxDeliveryReadOriginal,*,draft: TaxDeliveryDraft) -> TaxCalculatedDocumentsInspection:
        """Derive scope without dropping unsupported or unparsed documents.

        This is neither a known-job binding nor owner confirmation. Those must
        separately link the retained response, full inspection and current data.
        Rejected responses and all guidance/deviation counts remain visible.
        """
        try:
            response=self._response.inspect(original)
            self._delivery.validate_calculated_pair(response,draft=draft)
            root=_parse(original.raw_bytes)
            if root.find(_RESPONSE_NS+'informasjonOmPersonligSkattesubjekt') is not None:raise ValueError()
            subject=root.find(_RESPONSE_NS+'informasjonOmUpersonligSkattesubjekt')
            if subject is not None and any((subject.findtext(_RESPONSE_NS+field) or '').strip() in ('true','1') for field in _UNSUPPORTED_REGIMES):
                raise ValueError()
            # Construct first to reject every unsupported document type; none
            # can be silently omitted by the supported-schema dispatch below.
            result=TaxCalculatedDocumentsInspection(self.schema_sha256,draft.sha256,draft.envelope.source.company_id,
                draft.envelope.source.income_year,draft.current_document.party_number,response)
            for document in response.calculated_documents:
                if document.document_type not in self._optional_schemas:continue
                node=_parse(document.raw_bytes)
                if node.getroottree().docinfo.encoding.upper().replace('-','')!='UTF8':raise ValueError()
                self._optional_schemas[document.document_type].assertValid(node)
                if document.document_type=='summertSkattegrunnlagForVisningUpersonlig' and (
                        node.findtext(_SUMMARY_NS+'partsnummer')!=result.party_number
                        or node.findtext(_SUMMARY_NS+'inntektsaar')!=str(int(result.income_year))):raise ValueError()
            result.assert_original(original,draft)
            return result
        except (ValueError,TypeError,KeyError,AttributeError,etree.LxmlError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None

    def review_documents(self,original: TaxDeliveryReadOriginal,*,draft: TaxDeliveryDraft) -> TaxCalculatedDocumentsReview:
        inspection=self.inspect(original,draft=draft)
        try:
            reviews=[];projection_bytes=0
            for document in inspection.response.calculated_documents:
                root=_parse(document.raw_bytes);values=[]
                def retain(path,value):
                    nonlocal projection_bytes
                    if len(values)>=100000:raise ValueError('Tax calculated review field bound exceeded.')
                    field=TaxCalculatedReviewField(path,value)
                    projection_bytes+=len(json.dumps({'path':path,'value':value},ensure_ascii=False,
                        separators=(',',':'),allow_nan=False).encode('utf-8'))
                    # Repeated long ancestor paths can amplify a small XML
                    # original. Stop before materializing an oversized view.
                    if projection_bytes>24*1024*1024:raise ValueError('Tax calculated review byte bound exceeded.')
                    values.append(field)
                def visit(node,path):
                    for name,value in sorted(node.attrib.items()):
                        retain(path+'/@'+name,value)
                    if not len(node):retain(path,node.text or '')
                    elif node.text and node.text.strip():retain(path+'/#text',node.text)
                    counts={}
                    for child in node:
                        name=etree.QName(child).localname;counts[name]=counts.get(name,0)+1
                        visit(child,path+'/'+name+'['+str(counts[name])+']')
                        if child.tail and child.tail.strip():
                            retain(path+'/'+name+'['+str(counts[name])+']/#tail',child.tail)
                visit(root,'/'+etree.QName(root).localname+'[1]')
                reviews.append(TaxCalculatedDocumentReview(document.document_type,sha256(document.raw_bytes).hexdigest(),tuple(values)))
            return TaxCalculatedDocumentsReview(inspection,tuple(reviews))
        except (ValueError,TypeError,AttributeError,etree.LxmlError,RecursionError,OverflowError):
            raise CompanyTaxError.unavailable() from None
