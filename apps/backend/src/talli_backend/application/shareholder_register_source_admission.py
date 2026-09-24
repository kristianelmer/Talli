"""Short guarded RF source admission, with original-byte I/O completed first.

The yielded transaction is the only place a consequential consumer may persist
its decision. Returning a verified value after releasing this scope is not
approval or send authority.
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import AsyncContextManager, Protocol

from talli_backend.modules.corporate_governance.public import CorporateGovernanceYearEvidence
from talli_backend.modules.documents.public import (
    DocumentId, DocumentsSessionFactory, RetainedDocumentOriginalReceipt,
)
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, CompanyId, CorrelationId, IncomeYear


@dataclass(frozen=True, slots=True)
class Rf1086AdmissionCompany:
    company: rf.Rf1086Company
    identity_confirmed_at: str
    identity_locked_at: str


class Rf1086SourceAdmissionTransaction(Protocol):
    """All reads/assertions and the eventual write share the held company guard."""
    @property
    def actor_id(self) -> ActorId: ...
    async def company_identity(self) -> Rf1086AdmissionCompany: ...
    async def governance_evidence(self, correlation_id: CorrelationId) -> CorporateGovernanceYearEvidence: ...
    async def current_source(self) -> rf.Rf1086YearSourceSnapshot | None: ...
    async def source_preview(self, preview_id: rf.PreviewId) -> rf.Rf1086SourcePreview: ...
    async def bridge_source_preview(self, preview: rf.Rf1086SourcePreview) -> rf.PreviewId: ...
    async def read_source_approval_context(self, preview_id: rf.PreviewId,
            entitlement_id: str) -> rf.Rf1086SourceApprovalReview: ...
    async def append_source_approval(self, preview: rf.Rf1086SourcePreview, entitlement_id: str,
            manifest: rf.Rf1086SourceApprovalManifest, review_sha256: str) -> rf.Rf1086RecordedResult: ...
    async def assert_original(self, receipt: RetainedDocumentOriginalReceipt) -> None: ...
    async def read_correction_predecessor(self, query: rf.Rf1086SourceQuery,
            submission_id: rf.SubmissionId) -> rf.Rf1086CorrectionPredecessorSnapshot: ...
    async def read_current_register_observation(self, query: rf.Rf1086SourceQuery,
            observation_id: rf.Rf1086RegisterObservationId) -> rf.Rf1086RegisterObservationSnapshot | None: ...


class SourceAdmissionSession(Protocol):
    @property
    def actor_id(self) -> ActorId: ...
    async def source_preview(self, preview_id: rf.PreviewId) -> rf.Rf1086SourcePreview: ...
    async def read_year_source(self, query: rf.Rf1086SourceQuery,
            source_id: rf.Rf1086YearSourceId) -> rf.Rf1086YearSourceSnapshot | None: ...
    async def read_correction_predecessor(self, query: rf.Rf1086SourceQuery,
            submission_id: rf.SubmissionId) -> rf.Rf1086CorrectionPredecessorSnapshot: ...
    def source_admission(self, query: rf.Rf1086SourceQuery) -> AsyncContextManager[Rf1086SourceAdmissionTransaction]: ...


class SourceAdmissionSessions(Protocol):
    async def session(self, access_token: str) -> SourceAdmissionSession: ...


@dataclass(frozen=True, slots=True)
class AdmittedRf1086Source:
    source: rf.Rf1086YearSourceSnapshot
    preview: rf.Rf1086SourcePreview
    originals: tuple[RetainedDocumentOriginalReceipt, ...]
    transaction: Rf1086SourceAdmissionTransaction


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise rf.Rf1086YearSourceError(code)


class ShareholderRegisterSourceAdmission:
    def __init__(self, sessions: SourceAdmissionSessions, documents: DocumentsSessionFactory):
        self._sessions = sessions
        self._documents = documents

    async def prepare_review(self, access_token: str, *, company_id: CompanyId,
            income_year: IncomeYear, preview_id: rf.PreviewId, correlation_id: CorrelationId) -> rf.PreviewId:
        """Materialize the immutable review projection before releasing admission.

        Review preparation grants no approval or provider authority. Those
        operations must independently re-enter admission against current facts.
        """
        async with self.admit(access_token, company_id=company_id, income_year=income_year,
                preview_id=preview_id, correlation_id=correlation_id) as admitted:
            return await admitted.transaction.bridge_source_preview(admitted.preview)

    async def read_readiness(self, access_token: str, *, company_id: CompanyId,
            income_year: IncomeYear, preview_id: rf.PreviewId,
            correlation_id: CorrelationId) -> rf.Rf1086SourceReadinessProof:
        """Read source readiness after current evidence checks on the held connection.

        This is a point-in-time observation without approval, send, payment or
        release authority. Consumers must re-enter admission before deciding.
        No legacy annual readiness or review projection is written by this read.
        """
        async with self.admit(access_token, company_id=company_id, income_year=income_year,
                preview_id=preview_id, correlation_id=correlation_id) as admitted:
            return rf.build_rf1086_source_readiness(admitted.source, admitted.preview)

    @asynccontextmanager
    async def admit(self, access_token: str, *, company_id: CompanyId,
            income_year: IncomeYear, preview_id: rf.PreviewId, correlation_id: CorrelationId):
        from .shareholder_register_source_workflow import _document_projection, build_verified_source_context
        session = await self._sessions.session(access_token)
        query = rf.Rf1086SourceQuery(company_id, income_year, session.actor_id)
        preview = await session.source_preview(preview_id)
        _require(preview.preview_id == preview_id and preview.company_id == company_id
                 and preview.income_year == income_year, 'rf1086_source_preview_not_found')
        source = await session.read_year_source(query, preview.source_id)
        _require(source is not None, 'rf1086_source_not_found')
        rf.assert_rf1086_year_source_integrity(source)
        rf.assert_rf1086_source_preview_matches(preview, source)
        _require(source.company_id == company_id and source.income_year == income_year,
                 'rf1086_source_company_year_mismatch')
        documents = await self._documents.session(access_token)
        _require(documents.actor_id == session.actor_id, 'rf1086_source_owner_required')
        originals = []
        for expected in sorted(source.command.documents, key=lambda item: item.document_id):
            evidence = await documents.verify_document_evidence(DocumentId(expected.document_id))
            _require(_document_projection(evidence) == expected, 'rf1086_source_documents_unverified')
            receipt = evidence.retained_original
            _require(receipt is not None and receipt.document_id.value == expected.document_id
                     and receipt.company_id == company_id and receipt.source_income_year == expected.source_income_year
                     and receipt.metadata_sha256 == expected.metadata_sha256
                     and receipt.content_sha256 == expected.content_sha256 and receipt.byte_length == expected.byte_length,
                     'rf1086_source_documents_unverified')
            originals.append(receipt)
        async with session.source_admission(query) as transaction:
            _require(transaction.actor_id == session.actor_id, 'rf1086_source_owner_required')
            identity = await transaction.company_identity()
            current = await transaction.current_source()
            _require(current is not None, 'rf1086_source_changed')
            rf.assert_rf1086_year_source_integrity(current)
            locked_preview = await transaction.source_preview(preview_id)
            _require(locked_preview == preview, 'rf1086_source_preview_stale')
            for receipt in originals:
                await transaction.assert_original(receipt)
            view = await transaction.governance_evidence(correlation_id)
            # Share type/contact belong to the reviewed RF case, not the legal
            # company projection. Preserve them exactly as capture does.
            company = replace(source.command.case.company, org_number=identity.company.org_number,
                name=identity.company.name, address=identity.company.address,
                postal_code=identity.company.postal_code, city=identity.company.city,
                income_year=identity.company.income_year)
            identity_sha256 = rf.rf1086_year_source_digest({'company_id': str(company_id), 'company': company,
                'entity_type': 'AS', 'identity_confirmed_at': identity.identity_confirmed_at,
                'identity_locked_at': identity.identity_locked_at})
            context = await build_verified_source_context(transaction, source.command,
                company, identity_sha256, source.command.documents, view)
            rf.assert_rf1086_year_source_fresh(source, current_source_id=current.source_id,
                current_source_sha256=current.source_sha256, context=context)
            rf.assert_rf1086_source_preview_matches(locked_preview, current)
            yield AdmittedRf1086Source(source, locked_preview, tuple(originals), transaction)
