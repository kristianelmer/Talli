"""Retained current-return response and inspected identity for Tax preparation."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import re

from talli_backend.shared.kernel import IncomeYear, Timestamp
from .delivery import _digest, _reference


class TaxCurrentDocumentKind(StrEnum):
    DRAFT = 'skattemeldingUpersonligUtkast'
    FILED = 'skattemeldingUpersonligFastsatt'


@dataclass(frozen=True, slots=True)
class TaxCurrentDocumentResponse:
    organization_number: str
    income_year: IncomeYear
    raw_base64: str
    observed_at: Timestamp

    def __post_init__(self):
        if (type(self.organization_number) is not str or re.fullmatch('[0-9]{9}',self.organization_number) is None
                or type(self.income_year) is not IncomeYear or type(self.income_year.value) is not int
                or int(self.income_year) != 2025 or type(self.observed_at) is not Timestamp
                or type(self.raw_base64) is not str or len(self.raw_base64) > 12*1024*1024):
            raise ValueError('Current Tax response scope is unsupported.')
        raw = self.raw_bytes
        if not raw or len(raw) > 8*1024*1024 or base64.b64encode(raw).decode('ascii') != self.raw_base64:
            raise ValueError('Current Tax response original bytes are invalid.')

    @property
    def raw_bytes(self) -> bytes:
        return base64.b64decode(self.raw_base64,validate=True)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw_bytes).hexdigest()


@dataclass(frozen=True, slots=True)
class TaxCurrentDocument:
    response: TaxCurrentDocumentResponse
    document_reference: str
    party_number: str
    document_kind: TaxCurrentDocumentKind
    tax_xml_sha256: str
    schema_sha256: str

    def __post_init__(self):
        if (type(self.response) is not TaxCurrentDocumentResponse
                or type(self.document_kind) is not TaxCurrentDocumentKind
                or type(self.party_number) is not str or re.fullmatch('[0-9]{1,19}',self.party_number) is None):
            raise ValueError('Inspected current Tax identity is invalid.')
        _reference(self.document_reference,'current document reference')
        _digest(self.tax_xml_sha256)
        _digest(self.schema_sha256)


def _decode_current_document(value):
    if type(value) is not dict or set(value) != {'response','document_reference','party_number',
            'document_kind','tax_xml_sha256','schema_sha256'}:
        raise ValueError('Retained current Tax document is invalid.')
    response = value['response']
    if (type(response) is not dict or set(response) != {'organization_number','income_year','raw_base64','observed_at'}
            or type(response['income_year']) is not dict or set(response['income_year']) != {'value'}
            or type(response['income_year']['value']) is not int
            or type(response['observed_at']) is not dict or set(response['observed_at']) != {'value'}):
        raise ValueError('Retained current Tax response is invalid.')
    original = TaxCurrentDocumentResponse(response['organization_number'],IncomeYear(response['income_year']['value']),
        response['raw_base64'],Timestamp(datetime.fromisoformat(response['observed_at']['value'])))
    return TaxCurrentDocument(**(value | {'document_kind':TaxCurrentDocumentKind(value['document_kind']),
        'response':original}))
