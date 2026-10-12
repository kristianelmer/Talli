"""Actual RF/Document/Governance code; SQL, authority and annual owner reads are doubles."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256

from talli_backend.application.annual_data_compatibility import LegacyAnnualDataView
from talli_backend.application.shareholder_register_annual_documents import Rf1086AnnualDocumentInputs
from talli_backend.application.shareholder_register_annual_ledger import Rf1086AnnualLedgerInputs
from talli_backend.application.shareholder_register_annual_opening import Rf1086AnnualOpeningInputs
from talli_backend.application.shareholder_register_source_admission_v2 import ShareholderRegisterSourceAdmissionV2
from talli_backend.modules.banking.public import BankYearReconciliation, BankYearReconciliationEvidence
from talli_backend.modules.ledger.public import OpeningBankInput, PeriodLock, PeriodLockId
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import Money, Timestamp
from rf1086_guarded_capture_v2_fixture import CaptureHarness, source_row, CORRELATION
from test_rf1086_source_context_v2 import identity, NOW
from test_rf1086_source_preview import preview_source


class AdmissionHarnessV2:
    def __init__(self, monkeypatch, kind='loss_covering_reduction', count=1):
        self.base = CaptureHarness(monkeypatch, kind, count)
        self.source = self.base.capture()
        self.preview = preview_source(self.source)[0]
        text = rf.serialize_rf1086_source_preview(self.preview)
        self.capture = rf.Rf1086ArchiveSourcePreview(self.preview, text, sha256(text.encode()).hexdigest(),
            str(self.source.confirmed_by.subject), (self.source.confirmed_at + timedelta(seconds=1)).isoformat())
        self.stored_source = source_row(self.source)
        self.held_transform = lambda row: row
        self.capture_reads = []
        self.annual_calls = []
        self.scope = None
        self.authenticated_actors = {'synthetic-token':self.base.store.actor_id,
            'historical-token':self.base.store.actor_id}
        self.authentication_calls = []
        self.base.calls.clear()
        self.base.committed = False
        owner = self
        execute = self.base.connection.execute

        async def execute_with_saved_preview(sql, args=()):
            if 'from shareholder_register_filing.register_observations' in sql and owner.base.basis.current is None:
                cursor = await execute('select synthetic_missing_current_observation', ())
                cursor.row = None
                return cursor
            cursor = await execute(sql, args)
            if 'from shareholder_register_filing.source_previews p' in sql:
                expected = (str(owner.preview.preview_id), str(owner.source.company_id), int(owner.source.income_year))
                owner.capture_reads.append((owner.base.guard, args))
                retained = owner.capture
                row = dict(id=retained.preview.preview_id.value, company_id=str(retained.preview.company_id),
                    income_year=int(retained.preview.income_year), source_id=retained.preview.source_id.value,
                    source_sha256=retained.preview.source_sha256, case_sha256=retained.preview.case_sha256,
                    profile=retained.preview.rendering_profile, payload_text=retained.payload_text,
                    payload_sha256=retained.payload_sha256, created_by=retained.created_by,
                    created_at=retained.created_at, source_snapshot_text=rf.serialize_rf1086_year_source_v2(owner.source))
                cursor.row = (owner.held_transform(row) if owner.base.guard else row) if args == expected else None
            elif sql.startswith('select * from shareholder_register_filing.year_source_versions'):
                cursor.row = owner.stored_source if args == (owner.source.source_id.value,
                    str(owner.source.company_id), int(owner.source.income_year)) else None
            return cursor

        self.base.connection.execute = execute_with_saved_preview
        source_admission = self.base.store.source_admission
        self.annual = self._annual_values()

        @asynccontextmanager
        async def source_admission_with_annual(query):
            async with source_admission(query) as scope:
                owner.scope = scope
                for name in owner.annual:
                    async def read(*args, name=name):
                        scope._require_active()
                        assert owner.base.guard and scope._connection is owner.base.connection
                        owner.annual_calls.append(name)
                        value = owner.annual[name]
                        if isinstance(value, BaseException): raise value
                        return value
                    setattr(scope, name, read)
                yield scope

        self.base.store.source_admission = source_admission_with_annual
        class Sessions:
            async def session(self, token):
                actor = owner.authenticated_actors.get(token)
                owner.authentication_calls.append(actor)
                if actor != owner.base.store.actor_id:
                    raise rf.ShareholderRegisterFilingError.forbidden()
                return owner.base.store
        class Documents:
            async def session(self, token):
                if owner.authenticated_actors.get(token) != owner.base.store.actor_id:
                    raise rf.ShareholderRegisterFilingError.forbidden()
                service = await owner.base.workflow._documents.session(token)
                # Explicit authority double: current owner changes, retained creators do not.
                service._persistence.actor_id = owner.base.store.actor_id
                return service
        self.workflow = ShareholderRegisterSourceAdmissionV2(Sessions(), Documents())

    def _annual_values(self):
        company, year, actor = self.source.company_id, self.source.income_year, self.base.store.actor_id
        opening_id = identity(7001)
        return {
            'annual_opening_inputs': Rf1086AnnualOpeningInputs(company, year,
                (rf.Rf1086OpeningSource(company, rf.OpeningSnapshotId(opening_id), year, 'a'*64, 1),)),
            'annual_ledger_inputs': Rf1086AnnualLedgerInputs(company, year,
                (OpeningBankInput(opening_id, company, year, Money(Decimal('123.45'), 'NOK'), actor, Timestamp(NOW)),),
                (PeriodLock(PeriodLockId(identity(7002)), company, year, 'Reviewed period', actor, Timestamp(NOW), False),)),
            'bank_year_evidence': BankYearReconciliationEvidence(
                BankYearReconciliation(company, year, Timestamp(NOW), 3, 0, 0), 'b'*64),
            'annual_interview': LegacyAnnualDataView(identity(7003), company, year,
                {'bank_balance_confirmed': True, 'has_unpaid_items': False, 'authority_to_submit_confirmed': True},
                (), False, 0, NOW.isoformat(), NOW.isoformat()),
            'annual_document_inputs': Rf1086AnnualDocumentInputs(company, year, tuple(self.base.records.values())),
        }

    def arguments(self):
        return dict(company_id=self.source.company_id, income_year=self.source.income_year,
            preview_id=self.preview.preview_id, correlation_id=CORRELATION)

    async def admitted(self):
        async with self.workflow.admit('synthetic-token', **self.arguments()) as value:
            assert self.base.guard
            return value

    def read(self): return asyncio.run(self.admitted())
    def read_annual(self):
        return asyncio.run(self.workflow.read_annual_readiness_v2('synthetic-token', **self.arguments()))
