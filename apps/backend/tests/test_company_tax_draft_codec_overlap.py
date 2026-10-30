"""Reader-first overlap: both original codecs survive writer containment."""
import base64
from dataclasses import replace
from datetime import datetime, UTC
import hashlib
import json

from talli_backend.modules.company_tax_filing.public import decode_tax_delivery_draft
from talli_backend.modules.company_tax_filing.current_document import (
    TaxCurrentDocumentResponse, TaxCurrentDocument, TaxCurrentDocumentKind,
)
from talli_backend.shared.kernel import Timestamp
from test_company_tax_delivery_draft import draft


def test_compatible_reader_restores_both_codecs_without_changing_the_v1_fieldset(draft):
    legacy=decode_tax_delivery_draft(draft.canonical_json,draft.sha256)
    assert legacy.canonical_json==draft.canonical_json
    value=json.loads(legacy.canonical_json)
    assert value['version']=='company-tax-delivery-draft-v1'
    assert 'current_document' not in value['draft']
    raw=b'\xef\xbb\xbf<retained-original-for-codec-test/>'
    envelope=draft.envelope
    original=TaxCurrentDocumentResponse(envelope.source.organization_number,envelope.source.income_year,
        base64.b64encode(raw).decode(),Timestamp(datetime(2026,10,26,tzinfo=UTC)))
    current=TaxCurrentDocument(original,envelope.current_document_reference,'123456',TaxCurrentDocumentKind.DRAFT,
        hashlib.sha256(envelope.tax_xml.encode()).hexdigest(),envelope.schema_sha256)
    value=replace(draft,current_document=current)
    restored=decode_tax_delivery_draft(value.canonical_json,value.sha256)
    assert restored==value and restored.current_document.response.raw_bytes==raw
    assert restored.canonical_json==value.canonical_json
    assert decode_tax_delivery_draft(draft.canonical_json,draft.sha256)==legacy
