"""Staged v2 preview creation; existing routes and runtime grants are unchanged."""
from talli_backend.application.shareholder_register_source_admission_v2 import (
    ShareholderRegisterSourceAdmissionV2, SourceAdmissionV2Sessions,
)
from talli_backend.application.shareholder_register_source_workflow import _require
from talli_backend.modules.documents.public import DocumentsSessionFactory
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, CorrelationId, IncomeYear


class ShareholderRegisterSourcePreviewV2:
    def __init__(self, sessions: SourceAdmissionV2Sessions, documents: DocumentsSessionFactory):
        self._sessions = sessions
        self._admission = ShareholderRegisterSourceAdmissionV2(sessions, documents)

    async def generate(self, access_token: str, *, company_id: CompanyId, income_year: IncomeYear,
            source_id: rf.Rf1086YearSourceId, correlation_id: CorrelationId) -> rf.Rf1086ArchiveSourcePreview:
        session = await self._sessions.session(access_token)
        query = rf.Rf1086SourceQuery(company_id, income_year, session.actor_id)
        source = await session.read_year_source(query, source_id)
        _require(type(source) is rf.Rf1086YearSourceSnapshotV2 and source.source_id == source_id,
            'rf1086_source_not_found')
        _require(source.company_id == company_id and source.income_year == income_year,
            'rf1086_source_company_year_mismatch')
        persistence = _PreviewCapture(self._admission, access_token, correlation_id)
        # Public preparation runs before the persistence facade enters admission.
        await rf.create_rf1086_preparation_service(persistence).generate_source_preview(
            rf.GenerateRf1086SourcePreview(company_id, income_year, source))
        _require(type(persistence.capture) is rf.Rf1086ArchiveSourcePreview,
            'rf1086_source_preview_storage_invalid')
        return persistence.capture


class _PreviewCapture:
    def __init__(self, admission, access_token, correlation_id):
        self._admission, self._access_token, self._correlation_id = admission, access_token, correlation_id
        self.capture: rf.Rf1086ArchiveSourcePreview | None = None

    async def capture_source_preview(self, command, prepared):
        _require(type(prepared) is rf.Rf1086PreparedSourcePreview
            and prepared.source == command.source, 'rf1086_source_preview_stale')
        async with self._admission.admit_year_source(self._access_token,
                company_id=command.company_id, income_year=command.income_year,
                source_id=command.source.source_id, correlation_id=self._correlation_id) as admitted:
            _require(rf.serialize_rf1086_year_source_v2(admitted.source)
                == rf.serialize_rf1086_year_source_v2(prepared.source), 'rf1086_source_changed')
            self.capture = await admitted.transaction.capture_source_preview_v2(prepared)
            return self.capture.preview
