"""Complete correction fixtures; actual bytes, synthetic persistence/authority.

Both named reader ports are deliberate test seams for a before/after comparison.
They return projections of the same archive; production never falls back between
them. No SQL, authenticated ownership or fresh v2 writer is established here.
"""
import asyncio
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
import json
from types import MappingProxyType
from uuid import UUID

from talli_backend.application.shareholder_register_source_approval import ShareholderRegisterSourceApprovalWorkflow
from talli_backend.application.shareholder_register_source_claim import ShareholderRegisterSourceClaimWorkflow
from talli_backend.application.shareholder_register_source_correction import ShareholderRegisterSourceCorrection
from talli_backend.modules.documents import public as documents
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CorrelationId
from rf1086_retained_stream_fixture import original, original_query, retained_stream_fixture
from test_rf1086_archive_history import with_captures
from test_rf1086_retained_recovery_correction import legacy_terminal_archive
from test_rf1086_source_approval import ApprovalHarness, ENTITLEMENT
from test_rf1086_source_approval_archive import source_archive
from test_rf1086_source_preview import preview_source
from test_rf1086_source_submission_archive import source_submission_archive
from test_rf1086_year_source import ACTOR, NOW


def selected_snapshot(archive, submission_id):
    """Structural old-reader projection; deliberately performs no policy check."""
    submission = next(row for row in archive.production_submissions if row.id == submission_id.value)
    approval = next(row for row in archive.approvals if row.id == submission.approval_id)
    preview = next(row for row in archive.previews if row.id == approval.preview_id)
    return rf.Rf1086CorrectionPredecessorSnapshot(archive.company_id, archive.income_year,
        submission, approval, preview,
        tuple(sorted((row for row in archive.feedback_artifacts if row.submission_id == submission.id),
                     key=lambda row: (row.document_id, row.id))),
        tuple(sorted((row for row in archive.production_events if row.submission_id == submission.id
                      and row.operation_name.startswith('reconciliation:') and row.operation_state == 'succeeded'),
                     key=lambda row: (row.created_at, row.id))),
        next((row for row in archive.source_approval_lineage if row.approval_id == approval.id), None),
        next((row for row in archive.source_submission_claims if row.submission_id.value == submission.id), None))


@dataclass(frozen=True)
class CorrectionFixture:
    archive: rf.Rf1086ArchiveSnapshot
    originals: object

    @property
    def query(self):
        return rf.Rf1086ArchiveQuery(self.archive.company_id, self.archive.income_year, ACTOR)

    @property
    def predecessor(self):
        row = self.archive.production_submissions[-1]
        approval = next(item for item in self.archive.approvals if item.id == row.approval_id)
        return rf.Rf1086SourceCorrectionPredecessor(rf.SubmissionId(row.id),
            approval.manifest_hash, 'Reviewed retained correction')


def _complete_v1(archive):
    line = archive.source_approval_lineage[0]
    source, preview = line.source, line.source_preview
    payload = rf.serialize_rf1086_source_preview(preview)
    history = rf.Rf1086ArchiveSourceHistory((source,),
        rf.Rf1086ArchiveYearSourceHead(source.company_id, source.income_year, source.source_id,
                                     source.version, source.source_sha256),
        (), (rf.Rf1086ArchiveSourcePreview(preview, payload, sha256(payload.encode()).hexdigest(),
                                         line.approved_by, line.bridge.created_at),), (line.bridge,))
    return replace(archive, source_history=with_captures(history), overrides=(), withdrawal_capture_records=())


def _feedback_originals(archive, bound):
    originals, artifacts = {}, []
    for index, artifact in enumerate(archive.feedback_artifacts):
        value = original(8200 + index, document_id=artifact.document_id,
            document_type='authority_feedback', source_year=int(archive.income_year),
            content=f'receipt-{index}'.encode(), content_type=artifact.content_type,
            linked_to='production_filing_submission:' + artifact.submission_id,
            created_at=datetime.fromisoformat(artifact.retrieved_at))
        receipt = value.original.receipt
        originals[original_query(value)] = value
        artifacts.append(replace(artifact, sha256=receipt.content_sha256, byte_length=receipt.byte_length,
            original_id=receipt.original_id if bound else None,
            original_metadata_sha256=receipt.metadata_sha256 if bound else None,
            original_source_income_year=int(receipt.source_income_year) if bound else None,
            original_retained_at=receipt.retained_at.isoformat() if bound else None))
    hashes = tuple(row.sha256 for row in artifacts)
    events = tuple(replace(row, artifact_hashes=hashes) if row.operation_name.startswith('reconciliation:')
                   else row for row in archive.production_events)
    return replace(archive, feedback_artifacts=tuple(artifacts), production_events=events), originals


def correction_fixture(profile='source-v1', kind='formation', status='accepted', amendments=0,
                       bound_feedback=True):
    if profile == 'source-v3':
        if kind not in ('cash_issue', 'loss_covering_reduction'):
            raise ValueError('V3 baseline requires a real capital chain fixture')
        archive, originals = retained_stream_fixture(kind, amendments, status, bound_feedback=bound_feedback)
        if not bound_feedback:
            # The stream helper only materializes bound receipts. Here the legacy
            # branch needs actual current evidence too, not a generic fake value.
            archive, feedback = _feedback_originals(archive, False)
            originals.update(feedback)
    elif profile == 'source-v1':
        if kind not in ('no_activity', 'formation', 'dividend'):
            raise ValueError('This v1 fixture does not invent missing register captures')
        archive = _complete_v1(source_submission_archive(kind, status))
        archive, originals = _feedback_originals(archive, bound_feedback)
    elif profile == 'legacy-no-activity':
        archive = replace(legacy_terminal_archive(status), source_history=rf.Rf1086ArchiveSourceHistory(),
                          overrides=(), withdrawal_capture_records=())
        archive, originals = _feedback_originals(archive, bound_feedback)
    else:
        raise ValueError(profile)
    result = CorrectionFixture(archive, MappingProxyType(originals))
    # A genuine complete fixture must pass both owner correspondence and the
    # retained projector before any application test installs failure sentinels.
    rf.serialize_rf1086_archive_v6(archive, query=result.query)
    projected = rf.prepare_rf1086_retained_correction_predecessor(archive,
        query=result.query, predecessor=result.predecessor)
    assert projected == selected_snapshot(archive, result.predecessor.submission_id)
    return result


class RetainedCorrectionHarness(ApprovalHarness):
    """Unchanged v1 child admission around a complete retained parent fixture."""
    def __init__(self, fixture=None):
        super().__init__()
        self.fixture = fixture or correction_fixture()
        self.archive = self.locked_archive = self.fixture.archive
        self.prior = self.fixture.predecessor
        self.history = self.archive.production_submissions
        self.originals = dict(self.fixture.originals)
        self.prior_failure = None
        self.original_failure = False
        self.feedback_ids = {row.document_id for row in self.archive.feedback_artifacts}
        self.prior_documents = {}
        for query, value in self.originals.items():
            if query.document_id.value in self.feedback_ids:
                receipt = value.original.receipt
                self.prior_documents[query.document_id.value] = documents.VerifiedDocumentEvidence(
                    value.document, receipt.content_sha256, receipt.byte_length,
                    documents.DocumentStatus.STORED, receipt)
        # A v3 parent is a helper-only fixture while the fresh child writer is
        # still v1. Do not fabricate a v1 successor to a retained v2 source.
        self.outer_supported = not any(type(line.source) is rf.Rf1086YearSourceSnapshotV2
                                       for line in self.archive.source_approval_lineage)
        if self.outer_supported:
            self._materialize_current_child()
        base_sessions, base_documents = self.workflow._sessions, self.workflow._documents
        owner = self

        class Session:
            def __init__(self, delegate): self.delegate = delegate
            def __getattr__(self, name): return getattr(self.delegate, name)
            async def read_correction_predecessor(self, query, submission_id):
                assert not owner.held and submission_id == owner.prior.submission_id
                assert query.actor_id == self.actor_id
                owner.calls.append('prior_read')
                return selected_snapshot(owner.archive, submission_id)
            async def read_retained_correction_archive(self, query, submission_id):
                assert not owner.held and submission_id == owner.prior.submission_id
                assert query.actor_id == self.actor_id
                owner.calls.append('retained_prior_read')
                return owner.archive

        class Sessions:
            async def session(self, token): return Session(await base_sessions.session(token))

        class Documents:
            async def session(self, token):
                delegate = await base_documents.session(token)
                class Store:
                    @property
                    def actor_id(self): return owner.document_actor
                    async def verify_document_evidence(self, document_id):
                        if document_id.value not in owner.feedback_ids:
                            return await delegate.verify_document_evidence(document_id)
                        assert not owner.held
                        owner.calls.append('prior_bytes:' + document_id.value)
                        if owner.prior_failure: raise owner.prior_failure
                        return owner.prior_documents[document_id.value]
                    async def read_retained_evidence(self, query):
                        assert not owner.held
                        owner.calls.append('historical_bytes:' + query.document_id.value)
                        if owner.prior_failure: raise owner.prior_failure
                        if query not in owner.originals: raise documents.DocumentsError.not_found()
                        return owner.originals[query]
                return Store()

        old_assert = self.transaction.assert_original
        async def assert_original(receipt):
            if receipt.document_id.value not in owner.feedback_ids:
                return await old_assert(receipt)
            assert owner.held
            owner.calls.append('prior_original')
            if owner.original_failure: raise documents.DocumentsError.integrity_failed()
            assert receipt == owner.prior_documents[receipt.document_id.value].retained_original
        async def assert_historical_original(receipt):
            assert owner.held
            owner.calls.append('historical_original')
            if owner.original_failure: raise documents.DocumentsError.integrity_failed()
            query = documents.RetainedDocumentOriginalQuery(receipt.document_id, receipt.company_id,
                receipt.source_income_year, receipt.metadata_sha256, receipt.content_sha256, receipt.byte_length)
            assert receipt == owner.originals[query].original.receipt
        async def locked(query, submission_id):
            assert owner.held and query.actor_id == owner.transaction.actor_id
            assert submission_id == owner.prior.submission_id
            owner.calls.append('prior_lock')
            return selected_snapshot(owner.locked_archive, submission_id)
        async def retained_locked(query, submission_id):
            assert owner.held and query.actor_id == owner.transaction.actor_id
            assert submission_id == owner.prior.submission_id
            owner.calls.append('retained_prior_lock')
            return owner.locked_archive
        self.transaction.assert_original = assert_original
        self.transaction.assert_historical_original = assert_historical_original
        self.transaction.read_correction_predecessor = locked
        self.transaction.read_retained_correction_archive = retained_locked
        self.sessions, self.documents = Sessions(), Documents()
        self.correction = ShareholderRegisterSourceCorrection(self.sessions, self.documents)
        self.approval = ShareholderRegisterSourceApprovalWorkflow(self.sessions, self.documents)
        if self.outer_supported:
            self._install_child_persistence()
            # Build a real annual review through the unchanged application before
            # the observed test begins. Later sentinels never affect construction.
            asyncio.run(self.approval.read_review('token', company_id=self.archive.company_id,
                income_year=self.archive.income_year, preview_id=self.preview.preview_id,
                entitlement_id=ENTITLEMENT, correlation_id=CorrelationId('fixture-review')))
            self.assert_complete_archive()
            self.calls.clear()
            self.committed = False

    def _materialize_current_child(self):
        parent = self.archive.source_history.year_sources[-1] if self.archive.source_history.year_sources else None
        command = self.source.command
        if parent is not None:
            command = replace(command, supersedes_source_id=parent.source_id,
                supersedes_source_sha256=parent.source_sha256, correction_reason='Reviewed child source')
        instant = max(self.source.confirmed_at, parent.confirmed_at if parent else NOW) + timedelta(seconds=1)
        self.current = self.source = rf.prepare_rf1086_year_source(command,
            context=self.source_harness.context, previous=parent,
            source_id=rf.Rf1086YearSourceId(str(UUID(int=88401))), confirmed_at=instant)
        self.preview = replace(preview_source(self.source)[0], preview_id=rf.PreviewId(str(UUID(int=88400))))
        self.child_time = instant.isoformat()
        self.review = replace(self.review, preview_id=self.preview.preview_id, source_id=self.source.source_id,
                              source_sha256=self.source.source_sha256)
        payload = rf.serialize_rf1086_source_preview(self.preview)
        self.child_payload = payload
        self.child_payload_sha256 = sha256(payload.encode()).hexdigest()
        self.child_bridge = rf.Rf1086ArchiveSourceReviewBridge(self.preview.preview_id.value,
            str(self.archive.company_id), int(self.archive.income_year), self.source.source_id.value,
            self.source.source_sha256, self.child_payload_sha256, str(self.actor.subject), self.child_time)
        history = self.archive.source_history
        child = rf.Rf1086ArchiveSourcePreview(self.preview, payload, self.child_payload_sha256,
                                              str(self.actor.subject), self.child_time)
        history = with_captures(replace(history, year_sources=history.year_sources + (self.source,),
            year_source_head=rf.Rf1086ArchiveYearSourceHead(self.source.company_id, self.source.income_year,
                self.source.source_id, self.source.version, self.source.source_sha256),
            source_previews=history.source_previews + (child,)))
        self.archive = self.locked_archive = replace(self.archive, source_history=history)

    def _install_child_persistence(self):
        owner = self
        review_template = source_archive().source_approval_lineage[0].review_text
        old_bridge = self.transaction.bridge_source_preview
        old_read = self.transaction.read_source_approval_context
        old_append = self.transaction.append_source_approval

        async def bridge(preview):
            result = await old_bridge(preview)
            basis = rf.Rf1086SourceApprovalManifestBasis(owner.source, preview, owner.actor,
                ENTITLEMENT, 'a' * 64, owner.review.warning_codes, owner.prior)
            encoded = rf.build_rf1086_source_approval_manifest(basis)
            projection = rf.Rf1086PreviewRecord(preview.preview_id.value, str(owner.archive.company_id), None,
                int(owner.archive.income_year), 'aksjonaerregisteroppgaven', preview.readiness_status,
                preview.readiness_issues, preview.preview_text, preview.hovedskjema_xml,
                encoded.underskjema_xml, 'rf1086-full-year-v1', owner.child_time)
            def update(archive):
                return replace(archive,
                    previews=tuple(row for row in archive.previews if row.id != projection.id) + (projection,),
                    source_history=replace(archive.source_history,
                        review_bridges=tuple(row for row in archive.source_history.review_bridges
                            if row.preview_id != projection.id) + (owner.child_bridge,)))
            owner.archive, owner.locked_archive = update(owner.archive), update(owner.locked_archive)
            return result

        async def read(preview_id, entitlement_id, annual):
            await old_read(preview_id, entitlement_id, annual)
            basis = rf.Rf1086SourceApprovalManifestBasis(owner.source, owner.preview, owner.actor,
                ENTITLEMENT, 'a' * 64, annual.required_warning_codes, owner.prior, annual)
            encoded = rf.build_rf1086_source_approval_manifest(basis)
            review = json.loads(review_template)
            review.pop('storedReleaseReady')
            review.update(version='rf1086-source-review-v2', binding=asdict(owner.child_bridge),
                annualReadiness=json.loads(rf.serialize_rf1086_source_approval_manifest(encoded))['annualReadiness'],
                otherOverridesReady=True)
            review['scope'].update(previewId=preview_id.value, sourceId=owner.source.source_id.value,
                sourceSha256=owner.source.source_sha256, entitlementId=ENTITLEMENT,
                warningCodes=list(annual.required_warning_codes))
            review['pilot']['id'] = ENTITLEMENT
            owner.child_review_text = json.dumps(review, sort_keys=True, ensure_ascii=False)
            digest = sha256(owner.child_review_text.encode()).hexdigest()
            owner.review = replace(owner.review, review_sha256=digest, warning_codes=annual.required_warning_codes)
            return owner.review

        async def append(preview, entitlement_id, manifest, review_sha256):
            result = await old_append(preview, entitlement_id, manifest, review_sha256)
            approval = rf.Rf1086ApprovalRecord(result.record_id, ENTITLEMENT, preview.preview_id.value,
                str(owner.archive.company_id), str(owner.actor.subject), int(owner.archive.income_year),
                'aksjonaerregisteroppgaven', 'rf1086_full_year_v1', 'rf1086-source-production-v1',
                owner.child_payload_sha256, manifest.manifest_sha256, manifest.manifest,
                str(owner.actor.subject), owner.child_time, None, None)
            line = rf.Rf1086ArchiveSourceApprovalLineage(approval.id, approval.preview_id, approval.company_id,
                approval.income_year, owner.source.source_id.value, owner.source.source_sha256,
                owner.child_payload_sha256, rf.serialize_rf1086_source_approval_manifest(manifest),
                manifest.manifest_sha256, review_sha256, owner.child_review_text, str(owner.actor.subject),
                owner.child_time, owner.source, owner.preview, owner.child_bridge)
            def update(archive):
                return replace(archive,
                    approvals=tuple(row for row in archive.approvals if row.id != approval.id) + (approval,),
                    source_approval_lineage=tuple(row for row in archive.source_approval_lineage
                        if row.approval_id != approval.id) + (line,))
            owner.archive, owner.locked_archive = update(owner.archive), update(owner.locked_archive)
            owner.assert_complete_archive()
            return result
        self.transaction.bridge_source_preview = bridge
        self.transaction.read_source_approval_context = read
        self.transaction.append_source_approval = append

    def assert_complete_archive(self):
        query = rf.Rf1086ArchiveQuery(self.archive.company_id, self.archive.income_year, ACTOR)
        rf.serialize_rf1086_archive_v6(self.archive, query=query)
        rf.prepare_rf1086_retained_correction_predecessor(self.archive, query=query, predecessor=self.prior)

    def approve(self, **changes):
        if not self.outer_supported:
            raise ValueError('V3 fixture is helper-only; fresh v2 child writer remains closed')
        return super().approve(**changes)

    @property
    def prior_snapshot(self): return selected_snapshot(self.archive, self.prior.submission_id)
    @property
    def locked_snapshot(self): return selected_snapshot(self.locked_archive, self.prior.submission_id)

    async def prepare(self):
        return await self.correction.prepare('token', company_id=self.archive.company_id,
            income_year=self.archive.income_year, predecessor=self.prior)

    async def check_held(self, verified):
        session = await self.sessions.session('token')
        query = rf.Rf1086SourceQuery(self.archive.company_id, self.archive.income_year, self.actor)
        async with session.source_admission(query) as transaction:
            await self.correction.assert_admitted(verified, transaction)

    def make_claim_workflow(self):
        return RetainedCorrectionClaimHarness(self)


class RetainedCorrectionClaimHarness:
    """Use the real claim workflow, preserving its replay and admission order."""
    def __init__(self, h):
        self.h = h
        h.approve(predecessor=h.prior)
        manifest = h.writes[-1]
        self.approval_id = rf.ApprovalId(h.result.record_id)
        self.manifest_sha256 = manifest.manifest_sha256
        self.expected_head = h.prior.submission_id
        actual = next(row for row in h.archive.approvals if row.id == self.approval_id.value)
        line = next(row for row in h.archive.source_approval_lineage if row.approval_id == actual.id)
        self.retained = rf.Rf1086RetainedSourceApproval(actual, line.manifest_text)
        self.locked_retained = self.retained
        self.claim = rf.Rf1086SourceSubmissionClaim(rf.SubmissionId(str(UUID(int=88200))), self.approval_id,
            h.archive.company_id, h.archive.income_year, self.manifest_sha256,
            self.retained.approval.payload_hash, self.expected_head, h.actor, h.child_time)
        self.result = rf.Rf1086SourceSubmissionClaimResult(self.claim, True)
        self.existing = None
        self.on_read_approval = lambda: None
        owner = self
        class Session:
            def __init__(self, delegate): self.delegate = delegate
            def __getattr__(self, name): return getattr(self.delegate, name)
            async def read_source_submission_claim(self, *args):
                assert not h.held; h.calls.append('recover'); return owner.existing
            async def read_source_claim_approval(self, *args):
                assert not h.held; h.calls.append('approval'); owner.on_read_approval(); return owner.retained
        class Sessions:
            async def session(self, token): return Session(await h.sessions.session(token))
        async def read(*args):
            assert h.held; h.calls.append('locked_approval'); return owner.locked_retained
        async def recover(*args):
            assert h.held; h.calls.append('locked_recover'); return owner.existing
        async def claim(*args):
            assert h.held and args == (owner.approval_id, owner.manifest_sha256,
                                      owner.expected_head, h.last_annual)
            h.calls.append('claim'); return owner.result
        h.transaction.read_source_claim_approval = read
        h.transaction.read_source_submission_claim = recover
        h.transaction.claim_source_submission = claim
        self.workflow = ShareholderRegisterSourceClaimWorkflow(Sessions(), h.documents)
        h.calls.clear(); h.writes.clear(); h.committed = False

    def run(self):
        return asyncio.run(self.workflow.claim('token', approval_id=self.approval_id,
            manifest_sha256=self.manifest_sha256, expected_head=self.expected_head,
            correlation_id=CorrelationId('retained-correction-claim')))
