"""Reverify correction receipt bytes before guarded predecessor admission."""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import re
from uuid import UUID

from talli_backend.modules.documents.public import (
    DocumentId, DocumentRecord, DocumentStatus, RetainedDocumentOriginalReceipt, VerifiedDocumentEvidence,
    document_metadata_sha256, RetainedDocumentOriginalQuery, RetainedDocumentOriginalSnapshot,
)
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear


def _require(condition):
    if not condition:
        raise rf.Rf1086ProductionError('basis_unavailable')


@dataclass(frozen=True, slots=True)
class _SelectedCorrectionEvidence:
    """Exact selected owner wire; unrelated history is revalidated separately."""
    source_codec: str | None
    source_text: str | None
    preview_text: str | None
    source_captures: tuple[rf.Rf1086ArchiveCaptureRecord, ...]
    preview_captures: tuple[rf.Rf1086ArchiveSourcePreview, ...]


def _retained_predecessor(archive, query, predecessor):
    # The live port promises complete enumeration even for a legacy parent.
    # Portable legacy unknown-coverage semantics are not a store read result.
    _require(isinstance(archive, rf.Rf1086ArchiveSnapshot)
        and type(archive.source_history) is rf.Rf1086ArchiveSourceHistory
        and type(archive.overrides) is tuple
        and type(archive.withdrawal_capture_records) is tuple)
    return rf.prepare_rf1086_retained_correction_predecessor(archive,
        query=rf.Rf1086ArchiveQuery(query.company_id, query.income_year, query.actor_id),
        predecessor=predecessor)


def _selected_evidence(archive, snapshot):
    lineage = snapshot.source_approval_lineage
    if lineage is None:
        # The retained projector has already proved genuine legacy no-activity.
        return _SelectedCorrectionEvidence(None, None, None, (), ())
    source = lineage.source
    if type(source) is rf.Rf1086YearSourceSnapshot:
        codec, text = 'rf1086-year-source-v1', rf.serialize_rf1086_year_source(source)
    elif type(source) is rf.Rf1086YearSourceSnapshotV2:
        codec, text = 'rf1086-year-source-v2', rf.serialize_rf1086_year_source_v2(source)
    else:
        raise rf.Rf1086ProductionError('basis_unavailable')
    return _SelectedCorrectionEvidence(codec, text,
        rf.serialize_rf1086_source_preview(lineage.source_preview),
        tuple(row for row in archive.source_history.source_capture_records
              if row.record_id == lineage.source_id),
        tuple(row for row in archive.source_history.source_previews
              if row.preview.preview_id.value == lineage.preview_id))


@dataclass(frozen=True, slots=True)
class VerifiedRf1086Correction:
    company_id: CompanyId
    income_year: IncomeYear
    actor_id: ActorId
    predecessor: rf.Rf1086SourceCorrectionPredecessor
    snapshot: rf.Rf1086CorrectionPredecessorSnapshot
    originals: tuple[RetainedDocumentOriginalReceipt, ...]
    selected_evidence: _SelectedCorrectionEvidence


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
        archive = await session.read_retained_correction_archive(query,predecessor.submission_id)
        snapshot = _retained_predecessor(archive, query, predecessor)
        _require(snapshot.submission.user_id == str(session.actor_id.subject))
        selected_evidence = _selected_evidence(archive, snapshot)
        documents = await self._documents.session(access_token)
        _require(documents.actor_id == session.actor_id)
        originals = []
        for artifact in sorted(snapshot.artifacts,key=lambda row: (row.document_id,row.id)):
            if artifact.original_id is None:
                evidence = await documents.verify_document_evidence(DocumentId(artifact.document_id))
            else:
                retained = await documents.read_retained_evidence(RetainedDocumentOriginalQuery(
                    DocumentId(artifact.document_id), company_id, IncomeYear(artifact.original_source_income_year),
                    artifact.original_metadata_sha256, artifact.sha256, artifact.byte_length))
                _require(isinstance(retained, RetainedDocumentOriginalSnapshot))
                receipt, content = retained.original.receipt, retained.original.content
                _require(receipt.original_id == artifact.original_id
                    and receipt.metadata_sha256 == artifact.original_metadata_sha256
                    and int(receipt.source_income_year) == artifact.original_source_income_year
                    and receipt.retained_at == datetime.fromisoformat(artifact.original_retained_at)
                    and len(content) == artifact.byte_length and sha256(content).hexdigest() == artifact.sha256)
                evidence = VerifiedDocumentEvidence(retained.document, artifact.sha256,
                    artifact.byte_length, DocumentStatus.STORED, receipt)
            _require(isinstance(evidence,VerifiedDocumentEvidence))
            document, receipt = evidence.document, evidence.retained_original
            _require(isinstance(document,DocumentRecord)
                and document.document_id.value == artifact.document_id and document.company_id == company_id
                and document.income_year == income_year and document.document_type == 'authority_feedback'
                and document.created_by.kind is ActorKind.USER
                and str(document.created_by.subject) == snapshot.submission.user_id
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
        return VerifiedRf1086Correction(company_id,income_year,session.actor_id,predecessor,snapshot,tuple(originals),selected_evidence)

    async def assert_admitted(self, verified, transaction):
        _require(isinstance(verified,VerifiedRf1086Correction) and transaction.actor_id == verified.actor_id)
        query = rf.Rf1086SourceQuery(verified.company_id,verified.income_year,verified.actor_id)
        archive = await transaction.read_retained_correction_archive(query,verified.predecessor.submission_id)
        current = _retained_predecessor(archive, query, verified.predecessor)
        _require(current == verified.snapshot
            and _selected_evidence(archive, current) == verified.selected_evidence)
        artifacts = sorted(current.artifacts, key=lambda row: (row.document_id, row.id))
        _require(len(verified.originals) == len(artifacts))
        for artifact, receipt in zip(artifacts, verified.originals, strict=True):
            _require(receipt.document_id.value == artifact.document_id)
            if artifact.original_id is None:
                await transaction.assert_original(receipt)
            else:
                _require(receipt.original_id == artifact.original_id
                    and receipt.metadata_sha256 == artifact.original_metadata_sha256
                    and int(receipt.source_income_year) == artifact.original_source_income_year
                    and receipt.retained_at == datetime.fromisoformat(artifact.original_retained_at))
                await transaction.assert_historical_original(receipt)
