"""Actual held RF/annual/Docs code; SQL authority, Auth and storage are doubles."""
import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import json

from talli_backend.application.shareholder_register_source_approval_v3 import ShareholderRegisterSourceApprovalV3
from talli_backend.modules.shareholder_register_filing import public as rf
from rf1086_admission_v2_fixture import AdmissionHarnessV2
from test_rf1086_source_context_v2 import identity


class ApprovalHarnessV3:
    def __init__(self, monkeypatch, kind='no_activity', depth=0):
        self.admission = AdmissionHarnessV2(monkeypatch, kind, depth)
        self.base = self.admission.base
        self.source, self.capture = self.admission.source, self.admission.capture
        self.entitlement_id = identity(8801)
        self.approvals = {}
        self.bridges = set()
        self.contexts = []
        self.context_transform = lambda value: value
        self.after_context = lambda: None
        self.after_append = lambda: None
        self.result_transform = lambda row: row
        owner = self
        execute = self.base.connection.execute

        async def execute_with_approval(sql, args=()):
            cursor = await execute(sql, args)
            if 'from shareholder_register_filing.source_previews p' in sql and args == (owner.capture.preview.preview_id.value,):
                capture, preview = owner.capture, owner.capture.preview
                cursor.row = dict(id=preview.preview_id.value, company_id=str(preview.company_id),
                    income_year=int(preview.income_year), source_id=preview.source_id.value,
                    source_sha256=preview.source_sha256, case_sha256=preview.case_sha256,
                    profile=preview.rendering_profile, payload_text=capture.payload_text,
                    payload_sha256=capture.payload_sha256,
                    source_snapshot_text=rf.serialize_rf1086_year_source_v2(owner.source))
            elif 'production_filing_submissions ' in sql:
                cursor.row = None
            elif 'bridge_source_preview_v1(' in sql:
                assert owner.base.guard
                owner.bridges.add(args[0])
                cursor.row = {'id': args[0]}
            elif 'read_source_approval_context_v3(' in sql:
                assert owner.base.guard and owner.capture.preview.preview_id.value in owner.bridges
                preview_id, entitlement_id, annual_text, actor = args
                assert (preview_id, entitlement_id, actor) == (owner.capture.preview.preview_id.value,
                    owner.entitlement_id, str(owner.base.store.actor_id.subject))
                proof = json.loads(annual_text)['proof']['fields']
                value = dict(companyId=str(owner.source.company_id), incomeYear=int(owner.source.income_year),
                    previewId=preview_id, sourceId=owner.source.source_id.value,
                    sourceSha256=owner.source.source_sha256, entitlementId=entitlement_id,
                    warningCodes=proof['required_warning_codes'],
                    blockers=['annual_prerequisites_not_ready'] if proof['readiness_status'] == 'blocked' else [],
                    reviewSha256=sha256((annual_text + actor + entitlement_id).encode()).hexdigest())
                owner.contexts.append(value)
                cursor.row = {'context': owner.context_transform(dict(value))}
                owner.after_context()
            elif 'append_source_approval_v3(' in sql:
                assert owner.base.guard and owner.contexts
                preview_id, entitlement_id, text, digest, review_sha, actor = args
                assert sha256(text.encode()).hexdigest() == digest
                assert review_sha == owner.contexts[-1]['reviewSha256']
                key = identity(int(digest[:12], 16))
                owner.approvals.setdefault(key, dict(id=key, company_id=str(owner.source.company_id),
                    income_year=int(owner.source.income_year), payload_text=text, payload_sha256=digest,
                    actor=actor, entitlement_id=entitlement_id, preview_id=preview_id))
                cursor.row = owner.result_transform(owner.approvals[key])
                owner.after_append()
            return cursor
        async def fetchall():
            return []
        self.base.connection.execute = execute_with_approval
        self.base.connection.fetchall = fetchall
        transaction = self.base.store._transaction

        @asynccontextmanager
        async def transaction_with_approval(**options):
            before = dict(owner.approvals), set(owner.bridges)
            try:
                async with transaction(**options) as connection:
                    yield connection
            except BaseException:
                owner.approvals, owner.bridges = before
                raise
        self.base.store._transaction = transaction_with_approval
        self.workflow = ShareholderRegisterSourceApprovalV3(
            self.admission.workflow._sessions, self.admission.workflow._documents)

    def arguments(self):
        return dict(**self.admission.arguments(), entitlement_id=self.entitlement_id)

    def review(self):
        return asyncio.run(self.workflow.read_review('synthetic-token', **self.arguments()))

    def approve(self, review, **changes):
        arguments = dict(**self.arguments(), review_sha256=review.review.review_sha256,
            acknowledged_warning_codes=review.review.warning_codes, real_filing_confirmed=True)
        arguments.update(changes)
        return asyncio.run(self.workflow.approve('synthetic-token', **arguments))
