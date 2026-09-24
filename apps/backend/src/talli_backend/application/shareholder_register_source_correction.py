"""Reverify correction receipt bytes before guarded predecessor admission."""
from dataclasses import dataclass
from datetime import datetime
import re
from uuid import UUID

from talli_backend.modules.documents.public import (
    DocumentId, DocumentRecord, DocumentStatus, RetainedDocumentOriginalReceipt, VerifiedDocumentEvidence,
    document_metadata_sha256,
)
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, CompanyId, IncomeYear


def _require(condition):
    if not condition:
        raise rf.Rf1086ProductionError('basis_unavailable')


@dataclass(frozen=True, slots=True)
class VerifiedRf1086Correction:
    company_id: CompanyId
    income_year: IncomeYear
    actor_id: ActorId
    predecessor: rf.Rf1086SourceCorrectionPredecessor
    snapshot: rf.Rf1086CorrectionPredecessorSnapshot
    originals: tuple[RetainedDocumentOriginalReceipt, ...]


class ShareholderRegisterSourceCorrection:
    """Reusable preflight/final check; no provider operations or independent writes."""
    def __init__(self, sessions, documents):
        self._sessions, self._documents = sessions, documents

    async def prepare(self, access_token, *, company_id, income_year, predecessor):
        try:
            _require(isinstance(predecessor,rf.Rf1086SourceCorrectionPredecessor)
                and isinstance(predecessor.submission_id,rf.SubmissionId)
                and str(UUID(predecessor.submission_id.value)) == predecessor.submission_id.value
                and type(predecessor.manifest_sha256) is str
                and re.fullmatch('[a-f0-9]{64}',predecessor.manifest_sha256) is not None
                and type(predecessor.reason) is str and bool(predecessor.reason.strip()))
        except (ValueError,TypeError,AttributeError):
            raise rf.Rf1086ProductionError('basis_unavailable') from None
        session = await self._sessions.session(access_token)
        query = rf.Rf1086SourceQuery(company_id,income_year,session.actor_id)
        snapshot = await session.read_correction_predecessor(query,predecessor.submission_id)
        rf.assert_rf1086_correction_predecessor(snapshot,company_id=company_id,income_year=income_year,predecessor=predecessor)
        _require(snapshot.submission.user_id == str(session.actor_id.subject))
        documents = await self._documents.session(access_token)
        _require(documents.actor_id == session.actor_id)
        originals = []
        for artifact in sorted(snapshot.artifacts,key=lambda row: (row.document_id,row.id)):
            evidence = await documents.verify_document_evidence(DocumentId(artifact.document_id))
            _require(isinstance(evidence,VerifiedDocumentEvidence))
            document, receipt = evidence.document, evidence.retained_original
            _require(isinstance(document,DocumentRecord)
                and document.document_id.value == artifact.document_id and document.company_id == company_id
                and document.income_year == income_year and document.document_type == 'authority_feedback'
                and document.linked_to == 'production_filing_submission:'+snapshot.submission.id
                and document.content_type == artifact.content_type
                and document.status is DocumentStatus.STORED and evidence.integrity_status is DocumentStatus.STORED
                and document.removed_at is None
                and document.content_sha256 == evidence.content_sha256 == artifact.sha256
                and type(document.byte_length) is int and type(evidence.byte_length) is int
                and document.byte_length == evidence.byte_length == artifact.byte_length)
            _require(isinstance(receipt,RetainedDocumentOriginalReceipt)
                and receipt.document_id == document.document_id and receipt.company_id == company_id
                and receipt.source_income_year == income_year and receipt.content_sha256 == artifact.sha256
                and type(receipt.byte_length) is int and receipt.byte_length == artifact.byte_length
                and receipt.metadata_sha256 == document_metadata_sha256(document)
                and isinstance(receipt.retained_at,datetime) and receipt.retained_at.tzinfo is not None)
            try:
                _require(str(UUID(receipt.original_id)) == receipt.original_id)
            except (ValueError,TypeError,AttributeError):
                raise rf.Rf1086ProductionError('basis_unavailable') from None
            originals.append(receipt)
        return VerifiedRf1086Correction(company_id,income_year,session.actor_id,predecessor,snapshot,tuple(originals))

    async def assert_admitted(self, verified, transaction):
        _require(isinstance(verified,VerifiedRf1086Correction) and transaction.actor_id == verified.actor_id)
        query = rf.Rf1086SourceQuery(verified.company_id,verified.income_year,verified.actor_id)
        current = await transaction.read_correction_predecessor(query,verified.predecessor.submission_id)
        rf.assert_rf1086_correction_predecessor(current,company_id=verified.company_id,
            income_year=verified.income_year,predecessor=verified.predecessor)
        _require(current == verified.snapshot)
        for receipt in verified.originals:
            await transaction.assert_original(receipt)
