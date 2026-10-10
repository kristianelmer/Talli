"""Real RF/Docs/Governance and held adapters; SQL/auth/storage remain doubles."""
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from hashlib import sha256

from talli_backend.application.shareholder_register_source_preview_v2 import ShareholderRegisterSourcePreviewV2
from talli_backend.modules.shareholder_register_filing import public as rf
from rf1086_admission_v2_fixture import AdmissionHarnessV2


class PreviewHarnessV2:
    def __init__(self, monkeypatch, kind='loss_covering_reduction', count=1):
        self.admission = AdmissionHarnessV2(monkeypatch, kind, count)
        self.base = self.admission.base
        self.source = self.admission.source
        self.captures = {}
        self.saved_transform = lambda row: row
        self.fail_after_append = None
        self.held_proof_calls = []
        owner = self
        execute = self.base.connection.execute

        async def execute_with_preview(sql, args=()):
            cursor = await execute(sql, args)
            if 'prepare_rf_year_source_governance_proof' in sql:
                assert owner.base.guard
                owner.held_proof_calls.append(args)
            elif 'append_source_preview_v1(' in sql:
                assert owner.base.guard and owner.held_proof_calls
                preview_id, company_id, year, source_id, source_sha, case_sha, payload_sha, text = args
                parsed = rf.parse_rf1086_source_preview(text)
                assert (company_id, year, source_id, source_sha, case_sha) == (
                    str(owner.source.company_id), int(owner.source.income_year), owner.source.source_id.value,
                    owner.source.source_sha256, owner.source.case_sha256)
                assert sha256(text.encode()).hexdigest() == payload_sha
                if preview_id not in owner.captures:
                    owner.captures[preview_id] = rf.Rf1086ArchiveSourcePreview(parsed, text, payload_sha,
                        str(owner.base.store.actor_id.subject),
                        (owner.source.confirmed_at + timedelta(seconds=2)).isoformat())
                if owner.fail_after_append is not None: raise owner.fail_after_append
                cursor.row = {'id': preview_id}
            elif 'from shareholder_register_filing.source_previews p' in sql:
                capture = owner.captures.get(args[0])
                cursor.row = None
                if capture is not None:
                    row = dict(id=capture.preview.preview_id.value, company_id=str(capture.preview.company_id),
                        income_year=int(capture.preview.income_year), source_id=capture.preview.source_id.value,
                        source_sha256=capture.preview.source_sha256, case_sha256=capture.preview.case_sha256,
                        profile=capture.preview.rendering_profile, payload_text=capture.payload_text,
                        payload_sha256=capture.payload_sha256, created_by=capture.created_by,
                        created_at=capture.created_at, source_snapshot_text=rf.serialize_rf1086_year_source_v2(owner.source))
                    if args[1:] == (str(owner.source.company_id), int(owner.source.income_year)):
                        cursor.row = owner.saved_transform(row)
            return cursor
        self.base.connection.execute = execute_with_preview
        transaction = self.base.store._transaction

        @asynccontextmanager
        async def transaction_with_preview(**options):
            before = dict(owner.captures)
            try:
                async with transaction(**options) as connection: yield connection
            except BaseException:
                owner.captures = before
                raise
        self.base.store._transaction = transaction_with_preview
        self.workflow = ShareholderRegisterSourcePreviewV2(
            self.admission.workflow._sessions, self.admission.workflow._documents)

    def arguments(self):
        arguments = self.admission.arguments()
        arguments.pop('preview_id')
        arguments['source_id'] = self.source.source_id
        return arguments

    def generate(self):
        return asyncio.run(self.workflow.generate('synthetic-token', **self.arguments()))
