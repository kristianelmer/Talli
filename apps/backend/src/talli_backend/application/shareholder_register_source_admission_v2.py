"""Staged v2 admission: saved rendering, current evidence on one held scope."""
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import AsyncContextManager, Protocol

from talli_backend.application.annual_data_compatibility import LegacyAnnualDataView
from talli_backend.application.shareholder_register_annual_documents import Rf1086AnnualDocumentInputs
from talli_backend.application.shareholder_register_annual_ledger import Rf1086AnnualLedgerInputs
from talli_backend.application.shareholder_register_annual_opening import Rf1086AnnualOpeningInputs
from talli_backend.application.shareholder_register_source_admission import Rf1086AdmissionCompany
from talli_backend.application.shareholder_register_source_capture_v2 import assert_source_capture_originals_v2
from talli_backend.application.shareholder_register_source_context_v2 import build_verified_source_context_v2
from talli_backend.application.shareholder_register_source_workflow import _document_projection, _require
from talli_backend.modules.banking.public import BankYearReconciliationEvidence
from talli_backend.modules.corporate_governance.public import CorporateGovernanceYearRegisterEvidence
from talli_backend.modules.documents.public import DocumentId, DocumentsSessionFactory, RetainedDocumentOriginalReceipt
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, CompanyId, CorrelationId, IncomeYear


class SourceAdmissionV2Scope(Protocol):
    @property
    def actor_id(self) -> ActorId: ...
    async def company_identity(self) -> Rf1086AdmissionCompany: ...
    async def current_source(self) -> rf.Rf1086YearSourceSnapshot | rf.Rf1086YearSourceSnapshotV2 | None: ...
    async def retained_source_preview(self, preview_id: rf.PreviewId) -> rf.Rf1086ArchiveSourcePreview: ...
    async def capture_source_preview_v2(self, prepared: rf.Rf1086PreparedSourcePreview) -> rf.Rf1086ArchiveSourcePreview: ...
    async def assert_original(self, receipt: RetainedDocumentOriginalReceipt) -> None: ...
    async def governance_register_evidence(self, correlation_id: CorrelationId) -> CorporateGovernanceYearRegisterEvidence: ...
    async def read_current_register_observation(self, query: rf.Rf1086SourceQuery,
            observation_id: rf.Rf1086RegisterObservationId) -> rf.Rf1086RegisterObservationSnapshot | None: ...
    async def read_source_approval_context_v3(self, preview_id: rf.PreviewId, entitlement_id: str,
            correlation_id: CorrelationId) -> rf.Rf1086SourceApprovalContextV3: ...
    async def append_source_approval_v3(self, preview_id: rf.PreviewId, entitlement_id: str,
            manifest: rf.Rf1086SourceApprovalManifest, expected_review_sha256: str,
            correlation_id: CorrelationId) -> rf.Rf1086RecordedResult: ...
    async def submission_history(self) -> tuple[rf.Rf1086ProductionSubmissionRecord, ...]: ...
    async def annual_opening_inputs(self) -> Rf1086AnnualOpeningInputs: ...
    async def annual_ledger_inputs(self, correlation_id: CorrelationId) -> Rf1086AnnualLedgerInputs: ...
    async def bank_year_evidence(self, correlation_id: CorrelationId) -> BankYearReconciliationEvidence: ...
    async def annual_interview(self) -> LegacyAnnualDataView | None: ...
    async def annual_document_inputs(self) -> Rf1086AnnualDocumentInputs: ...


class SourceAdmissionV2Session(Protocol):
    @property
    def actor_id(self) -> ActorId: ...
    async def retained_source_preview(self, query: rf.Rf1086SourceQuery,
            preview_id: rf.PreviewId) -> rf.Rf1086ArchiveSourcePreview: ...
    async def read_year_source(self, query: rf.Rf1086SourceQuery,
            source_id: rf.Rf1086YearSourceId) -> rf.Rf1086YearSourceSnapshot | rf.Rf1086YearSourceSnapshotV2 | None: ...
    def source_admission(self, query: rf.Rf1086SourceQuery) -> AsyncContextManager[SourceAdmissionV2Scope]: ...


class SourceAdmissionV2Sessions(Protocol):
    async def session(self, access_token: str) -> SourceAdmissionV2Session: ...


@dataclass(frozen=True, slots=True)
class AdmittedRf1086YearSourceV2:
    source: rf.Rf1086YearSourceSnapshotV2
    originals: tuple[RetainedDocumentOriginalReceipt, ...]
    transaction: SourceAdmissionV2Scope


@dataclass(frozen=True, slots=True)
class AdmittedRf1086SourceV2:
    source: rf.Rf1086YearSourceSnapshotV2
    retained_preview: rf.Rf1086ArchiveSourcePreview
    source_readiness: rf.Rf1086SourceReadinessProofV2
    originals: tuple[RetainedDocumentOriginalReceipt, ...]
    transaction: SourceAdmissionV2Scope

    @property
    def preview(self):
        return self.retained_preview.preview


class ShareholderRegisterSourceAdmissionV2:
    """Existing routes are unchanged; yielded scopes confer no authority after release."""
    def __init__(self, sessions: SourceAdmissionV2Sessions, documents: DocumentsSessionFactory):
        self._sessions, self._documents = sessions, documents

    @asynccontextmanager
    async def admit(self, access_token: str, *, company_id: CompanyId, income_year: IncomeYear,
            preview_id: rf.PreviewId, correlation_id: CorrelationId):
        session = await self._sessions.session(access_token)
        query = rf.Rf1086SourceQuery(company_id, income_year, session.actor_id)
        retained = await session.retained_source_preview(query, preview_id)
        _require(type(retained) is rf.Rf1086ArchiveSourcePreview
            and retained.preview.preview_id == preview_id and retained.preview.company_id == company_id
            and retained.preview.income_year == income_year, 'rf1086_source_preview_not_found')
        source = await session.read_year_source(query, retained.preview.source_id)
        _require(type(source) is rf.Rf1086YearSourceSnapshotV2, 'rf1086_source_not_found')
        _require(source.company_id == company_id and source.income_year == income_year,
            'rf1086_source_company_year_mismatch')
        rf.build_rf1086_retained_source_readiness_v2(source, retained)
        originals = await self._verify_originals(access_token, session, source)
        async with self._admit_source(session, query, source, originals, correlation_id, retained) as admitted:
            readiness = rf.build_rf1086_retained_source_readiness_v2(source, retained)
            yield AdmittedRf1086SourceV2(source, retained, readiness, originals, admitted.transaction)

    @asynccontextmanager
    async def admit_year_source(self, access_token: str, *, company_id: CompanyId,
            income_year: IncomeYear, source_id: rf.Rf1086YearSourceId, correlation_id: CorrelationId):
        session = await self._sessions.session(access_token)
        query = rf.Rf1086SourceQuery(company_id, income_year, session.actor_id)
        source = await session.read_year_source(query, source_id)
        _require(type(source) is rf.Rf1086YearSourceSnapshotV2 and source.source_id == source_id,
            'rf1086_source_not_found')
        _require(source.company_id == company_id and source.income_year == income_year,
            'rf1086_source_company_year_mismatch')
        rf.assert_rf1086_year_source_integrity_v2(source)
        originals = await self._verify_originals(access_token, session, source)
        async with self._admit_source(session, query, source, originals, correlation_id) as admitted:
            yield admitted

    async def _verify_originals(self, access_token, session, source):
        documents = await self._documents.session(access_token)
        _require(documents.actor_id == session.actor_id, 'rf1086_source_owner_required')
        originals = []
        for expected in sorted(source.command.documents, key=lambda item: item.document_id):
            evidence = await documents.verify_document_evidence(DocumentId(expected.document_id))
            _require(_document_projection(evidence) == expected, 'rf1086_source_documents_unverified')
            originals.append(evidence.retained_original)
        originals = tuple(originals)
        assert_source_capture_originals_v2(source.command, originals)
        return originals

    @asynccontextmanager
    async def _admit_source(self, session, query, source, originals, correlation_id,
            retained: rf.Rf1086ArchiveSourcePreview | None = None):
        company_id = query.company_id
        async with session.source_admission(query) as transaction:
            _require(transaction.actor_id == session.actor_id, 'rf1086_source_owner_required')
            identity = await transaction.company_identity()
            current = await transaction.current_source()
            _require(type(current) is rf.Rf1086YearSourceSnapshotV2
                and rf.serialize_rf1086_year_source_v2(current) == rf.serialize_rf1086_year_source_v2(source),
                'rf1086_source_changed')
            if retained is not None:
                locked = await transaction.retained_source_preview(retained.preview.preview_id)
                _require(locked == retained, 'rf1086_source_preview_stale')
            for receipt in originals: await transaction.assert_original(receipt)
            view = await transaction.governance_register_evidence(correlation_id)
            company = replace(source.command.case.company, org_number=identity.company.org_number,
                name=identity.company.name, address=identity.company.address,
                postal_code=identity.company.postal_code, city=identity.company.city,
                income_year=identity.company.income_year)
            identity_sha = rf.rf1086_year_source_digest({'company_id': str(company_id), 'company': company,
                'entity_type': 'AS', 'identity_confirmed_at': identity.identity_confirmed_at,
                'identity_locked_at': identity.identity_locked_at})
            # Current actor authorizes only live reads. This authorization copy
            # is never serialized or persisted; historical command/actor stay.
            authorized_command = replace(source.command, actor_id=session.actor_id)
            context = await build_verified_source_context_v2(transaction, authorized_command,
                company, identity_sha, source.command.documents, view)
            rf.assert_rf1086_year_source_fresh_v2(source, current_source_id=current.source_id,
                current_source_sha256=current.source_sha256, context=context)
            yield AdmittedRf1086YearSourceV2(source, originals, transaction)

    async def read_readiness_v2(self, access_token: str, *, company_id: CompanyId,
            income_year: IncomeYear, preview_id: rf.PreviewId, correlation_id: CorrelationId):
        async with self.admit(access_token, company_id=company_id, income_year=income_year,
                preview_id=preview_id, correlation_id=correlation_id) as admitted:
            return admitted.source_readiness

    async def read_annual_readiness_v2(self, access_token: str, *, company_id: CompanyId,
            income_year: IncomeYear, preview_id: rf.PreviewId, correlation_id: CorrelationId):
        async with self.admit(access_token, company_id=company_id, income_year=income_year,
                preview_id=preview_id, correlation_id=correlation_id) as admitted:
            inputs = await _annual_inputs_v2(admitted, correlation_id)
            return rf.build_rf1086_retained_annual_readiness_v2(
                admitted.source, admitted.retained_preview, inputs)


def _scope(value, expected_type, source):
    if (not isinstance(value, expected_type) or value.company_id != source.company_id
            or value.income_year != source.income_year):
        raise rf.Rf1086YearSourceError('rf1086_annual_inputs_unavailable')


async def _annual_inputs_v2(admitted, correlation_id):
    return await read_rf1086_current_annual_inputs_v2(admitted.transaction, admitted.source, correlation_id)


async def read_rf1086_current_annual_inputs_v2(transaction, source, correlation_id):
    """The frozen owner read order and annual input fields, without legacy rendering."""
    opening = await transaction.annual_opening_inputs()
    _scope(opening, Rf1086AnnualOpeningInputs, source)
    ledger = await transaction.annual_ledger_inputs(correlation_id)
    _scope(ledger, Rf1086AnnualLedgerInputs, source)
    banking = await transaction.bank_year_evidence(correlation_id)
    if not isinstance(banking, BankYearReconciliationEvidence):
        raise rf.Rf1086YearSourceError('rf1086_annual_inputs_unavailable')
    reconciliation = banking.reconciliation
    if reconciliation.company_id != source.company_id or reconciliation.income_year != source.income_year:
        raise rf.Rf1086YearSourceError('rf1086_annual_inputs_unavailable')
    interview = await transaction.annual_interview()
    if interview is not None: _scope(interview, LegacyAnnualDataView, source)
    documents = await transaction.annual_document_inputs()
    _scope(documents, Rf1086AnnualDocumentInputs, source)
    answers = interview.answers if interview is not None else {}
    return rf.Rf1086AnnualReadinessInputs(
        company_id=source.company_id, income_year=source.income_year,
        opening_snapshot_ids=tuple(sorted(str(item.opening_snapshot_id) for item in opening.opening_sources)),
        opening_bank_snapshot_ids=tuple(sorted(item.snapshot_id for item in ledger.opening_bank_inputs)),
        period_lock_ids=tuple(sorted(str(item.period_lock_id) for item in ledger.period_locks)),
        bank_transaction_count=reconciliation.transaction_count,
        unmatched_bank_count=reconciliation.unmatched_count,
        accepted_bank_warning_count=reconciliation.accepted_warning_count,
        interview_source_id=interview.source_id if interview is not None else None,
        bank_balance_confirmed=answers.get('bank_balance_confirmed', False) if interview is not None else None,
        has_unpaid_items=answers.get('has_unpaid_items', False) if interview is not None else None,
        authority_to_submit_confirmed=answers.get('authority_to_submit_confirmed', False) if interview is not None else None,
        documents=tuple(sorted((rf.Rf1086AnnualDocumentStatus(str(item.document_id), item.linked_to, item.status.value)
            for item in documents.documents), key=lambda item: item.document_id)),
        evidence_sha256={'opening': rf.rf1086_year_source_digest(opening),
            'ledger': rf.rf1086_year_source_digest(ledger), 'banking': banking.source_sha256,
            'interview': rf.rf1086_year_source_digest(interview), 'documents': rf.rf1086_year_source_digest(documents)})
