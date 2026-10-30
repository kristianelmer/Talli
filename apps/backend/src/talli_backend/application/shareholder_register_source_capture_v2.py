"""V2 capture: committed replay first, original bytes before guarded append.

The atomic persistence method still depends on deployment-owned SQL execute
permissions; application composition does not grant them.
"""
from dataclasses import replace
from typing import Protocol

from talli_backend.application.shareholder_register_source_workflow import _document_projection, _require
from talli_backend.modules.company_access.public import CompanyAccessService
from talli_backend.modules.documents.public import (
    DocumentId, DocumentsSessionFactory, RetainedDocumentOriginalReceipt,
)
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, CorrelationId, IdempotencyKey


class SourceCaptureV2Session(Protocol):
    @property
    def actor_id(self) -> ActorId: ...
    async def read_year_source_capture_receipt(self, command: rf.RecordRf1086YearSource, *,
            idempotency_key: IdempotencyKey) -> rf.Rf1086YearSourceSnapshot | rf.Rf1086YearSourceSnapshotV2 | None: ...
    async def record_year_source_v2(self, command: rf.RecordRf1086YearSource, *,
            originals: tuple[RetainedDocumentOriginalReceipt, ...], idempotency_key: IdempotencyKey,
            correlation_id: CorrelationId) -> rf.Rf1086YearSourceSnapshot | rf.Rf1086YearSourceSnapshotV2: ...


class SourceCaptureV2Sessions(Protocol):
    async def session(self, access_token: str) -> SourceCaptureV2Session: ...


def assert_source_capture_originals_v2(command, originals):
    """Require the exact command union; SQL separately verifies stored originals."""
    _require(type(command) is rf.RecordRf1086YearSource
        and bool(command.documents)
        and all(type(item) is rf.Rf1086YearDocumentEvidence for item in command.documents)
        and len({item.document_id for item in command.documents}) == len(command.documents)
        and type(originals) is tuple
        and all(type(item) is RetainedDocumentOriginalReceipt for item in originals)
        and len({item.document_id.value for item in originals}) == len(originals)
        and len(originals) == len(command.documents), 'rf1086_source_documents_unverified')
    by_id = {item.document_id.value: item for item in originals}
    for expected in command.documents:
        receipt = by_id.get(expected.document_id)
        _require(receipt is not None and receipt.company_id == expected.company_id == command.company_id
            and receipt.source_income_year == expected.source_income_year
            and receipt.metadata_sha256 == expected.metadata_sha256
            and receipt.content_sha256 == expected.content_sha256
            and receipt.byte_length == expected.byte_length, 'rf1086_source_documents_unverified')


class ShareholderRegisterSourceCaptureV2:
    def __init__(self, sessions: SourceCaptureV2Sessions, company_access: CompanyAccessService,
            documents: DocumentsSessionFactory):
        self._sessions, self._company_access, self._documents = sessions, company_access, documents

    async def capture_year_source(self, access_token: str, command: rf.RecordRf1086YearSource, *,
            idempotency_key: IdempotencyKey, correlation_id: CorrelationId
    ) -> rf.Rf1086YearSourceSnapshot | rf.Rf1086YearSourceSnapshotV2:
        session = await self._sessions.session(access_token)
        _require(type(command) is rf.RecordRf1086YearSource and session.actor_id == command.actor_id,
            'rf1086_source_owner_required')
        replay = await session.read_year_source_capture_receipt(command, idempotency_key=idempotency_key)
        if replay is not None:
            return replay
        company = (await self._company_access.company_record(
            access_token, company_id=str(command.company_id))).company
        _require(company.id == str(command.company_id) and company.role == 'owner' and company.entity_type == 'AS'
            and company.identity_confirmed_at is not None and company.identity_locked_at is not None,
            'rf1086_source_owner_required')
        current_company = replace(command.case.company, org_number=company.org_number, name=company.name,
            address=company.address, postal_code=company.postal_code, city=company.city,
            income_year=int(command.income_year))
        _require(current_company == command.case.company, 'rf1086_source_company_year_mismatch')
        _require(bool(command.documents)
            and all(type(item) is rf.Rf1086YearDocumentEvidence and item.company_id == command.company_id
                for item in command.documents)
            and len({item.document_id for item in command.documents}) == len(command.documents),
            'rf1086_source_documents_unverified')
        documents = await self._documents.session(access_token)
        _require(documents.actor_id == session.actor_id, 'rf1086_source_owner_required')
        originals = []
        for expected in sorted(command.documents, key=lambda item: item.document_id):
            evidence = await documents.verify_document_evidence(DocumentId(expected.document_id))
            _require(_document_projection(evidence) == expected, 'rf1086_source_documents_unverified')
            originals.append(evidence.retained_original)
        originals = tuple(originals)
        assert_source_capture_originals_v2(command, originals)
        return await session.record_year_source_v2(command, originals=originals,
            idempotency_key=idempotency_key, correlation_id=correlation_id)
